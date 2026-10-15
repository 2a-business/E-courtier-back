import pytest
from django.test import override_settings

from apps.contracts.models import Contract
from apps.transactions.models import Transaction
from apps.visits import services as visit_services
from conftest import client_for, make_listing, make_slot, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def visited(listing, customer):
    visit = visit_services.book_visit(customer=customer, slot_id=make_slot(listing).pk)
    visit_services.change_status(actor=listing.owner, visit=visit, target="CONFIRMED")
    return listing


def create(customer, listing, key=""):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return client_for(customer).post("/api/v1/transactions/", {"listing": str(listing.pk)}, format="json", **headers)


def test_requires_confirmed_visit(listing, customer):
    res = create(customer, listing)
    assert res.status_code == 400 and res.data["code"] == "visit_required"


def test_amounts_computed_server_side_and_fee_separate(visited, customer):
    res = create(customer, visited)
    assert res.status_code == 201
    assert res.data["amount"] == 250000 and res.data["fee_amount"] == 5000 and res.data["total_amount"] == 255000
    assert res.data["amount_kind"] == "FIRST_MONTH_RENT" and res.data["status"] == "PENDING"
    assert res.data["currency"] == "XOF" and res.data["is_simulated"] is False


def test_sale_deposit_percentage(owner, customer):
    listing = make_listing(owner, transaction_type="SALE", price=100_000_000)
    quote = client_for(customer).get("/api/v1/transactions/quote/", {"listing": str(listing.pk)}).data
    assert quote["amount"] == 10_000_000 and quote["fee_amount"] == 5000 and quote["amount_kind"] == "RESERVATION_DEPOSIT"


def test_idempotency_and_no_duplicate_pending(visited, customer):
    first = create(customer, visited, key="abc-123")
    again = create(customer, visited, key="abc-123")
    third = create(customer, visited)
    assert first.status_code == 201 and again.status_code == 200 and third.status_code == 200
    assert first.data["id"] == again.data["id"] == third.data["id"]
    assert Transaction.objects.count() == 1


def test_wave_not_configured_returns_503(visited, customer):
    tx = create(customer, visited).data
    with override_settings(WAVE_PAYMENT_LINK=""):
        res = client_for(customer).post(f"/api/v1/transactions/{tx['id']}/wave/")
    assert res.status_code == 503 and res.data["code"] == "payment_not_configured"


def test_wave_flow_stays_pending_until_admin_confirms(visited, customer, admin):
    tx = create(customer, visited).data
    c = client_for(customer)
    res = c.post(f"/api/v1/transactions/{tx['id']}/wave/")
    assert res.status_code == 200 and res.data["checkout"]["url"].startswith("https://pay.wave.com/")
    assert res.data["checkout"]["auto_confirmation"] is False
    res = c.post(f"/api/v1/transactions/{tx['id']}/declare/", {"provider_reference": "T_ABC123456"}, format="json")
    assert res.status_code == 200 and res.data["status"] == "PENDING"
    assert res.data["attempts"][0]["status"] == "CUSTOMER_DECLARED"
    # Le client ne peut pas confirmer lui-même.
    assert c.post(f"/api/v1/admin/transactions/{tx['id']}/confirm/", {"provider_reference": "T_ABC123456"}, format="json").status_code == 403
    res = client_for(admin).post(f"/api/v1/admin/transactions/{tx['id']}/confirm/", {"provider_reference": "T_ABC123456"}, format="json")
    assert res.status_code == 200 and res.data["status"] == "PAID" and res.data["is_simulated"] is False
    assert res.data["contract"]["status"] == "DRAFT"
    events = [e["event"] for e in res.data["events"]]
    assert events == ["created", "payment_started", "payment_declared", "paid_confirmed"]


def test_duplicate_wave_reference_rejected(owner, admin):
    refs = []
    for _ in range(2):
        listing = make_listing(owner)
        cust = make_user()
        v = visit_services.book_visit(customer=cust, slot_id=make_slot(listing).pk)
        visit_services.change_status(actor=owner, visit=v, target="CONFIRMED")
        refs.append(create(cust, listing).data["id"])
    a = client_for(admin)
    assert a.post(f"/api/v1/admin/transactions/{refs[0]}/confirm/", {"provider_reference": "WAVE-REF-0001"}, format="json").status_code == 200
    res = a.post(f"/api/v1/admin/transactions/{refs[1]}/confirm/", {"provider_reference": "wave-ref-0001"}, format="json")
    assert res.status_code == 409 and res.data["code"] == "duplicate_reference"


def test_simulation_flagged_and_creates_demo_contract(visited, customer):
    tx = create(customer, visited).data
    res = client_for(customer).post(f"/api/v1/transactions/{tx['id']}/simulate/")
    assert res.data["status"] == "PAID" and res.data["is_simulated"] and res.data["provider"] == "SIMULATION"
    contract = Contract.objects.get(transaction_id=tx["id"])
    assert contract.is_simulated and "DÉMONSTRATION" in contract.current_version.content
    # Paiement non rejouable.
    assert client_for(customer).post(f"/api/v1/transactions/{tx['id']}/simulate/").status_code == 409


@override_settings(PAYMENT_SIMULATION_ENABLED=False)
def test_simulation_disabled(visited, customer):
    tx = create(customer, visited).data
    res = client_for(customer).post(f"/api/v1/transactions/{tx['id']}/simulate/")
    assert res.status_code == 403 and res.data["code"] == "simulation_disabled"
    assert Transaction.objects.get(pk=tx["id"]).status == "PENDING"


def test_listing_cannot_be_paid_twice(visited, customer, owner):
    tx = create(customer, visited).data
    client_for(customer).post(f"/api/v1/transactions/{tx['id']}/simulate/")
    other = make_user()
    v = visit_services.book_visit(customer=other, slot_id=make_slot(visited, 96).pk)
    visit_services.change_status(actor=owner, visit=v, target="CONFIRMED")
    res = create(other, visited)
    assert res.status_code == 409 and res.data["code"] == "listing_taken"


def test_cancel_and_refund(visited, customer, admin):
    tx = create(customer, visited).data
    c = client_for(customer)
    assert c.post(f"/api/v1/transactions/{tx['id']}/cancel/", {}, format="json").data["status"] == "CANCELLED"
    assert c.post(f"/api/v1/transactions/{tx['id']}/simulate/").status_code == 409
    tx2 = create(customer, visited).data
    c.post(f"/api/v1/transactions/{tx2['id']}/simulate/")
    a = client_for(admin)
    assert a.post(f"/api/v1/admin/transactions/{tx2['id']}/status/", {"status": "REFUNDED"}, format="json").status_code == 400
    res = a.post(f"/api/v1/admin/transactions/{tx2['id']}/status/", {"status": "REFUNDED", "note": "Désistement"}, format="json")
    assert res.data["status"] == "REFUNDED" and res.data["contract"]["status"] == "CANCELLED"


def test_privacy_of_transactions(visited, customer):
    tx = create(customer, visited).data
    assert client_for(make_user()).get(f"/api/v1/transactions/{tx['id']}/").status_code == 403
    assert client_for(visited.owner).get(f"/api/v1/transactions/{tx['id']}/").status_code == 200
    assert client_for(visited.owner).get("/api/v1/transactions/", {"role": "owner"}).data[0]["id"] == tx["id"]
