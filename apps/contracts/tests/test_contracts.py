import pytest

from apps.transactions import services as tx_services
from apps.visits import services as visit_services
from conftest import client_for, make_slot, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def contract(listing, customer):
    v = visit_services.book_visit(customer=customer, slot_id=make_slot(listing).pk)
    visit_services.change_status(actor=listing.owner, visit=v, target="CONFIRMED")
    tx, _ = tx_services.create_transaction(customer=customer, listing_id=listing.pk)
    tx_services.simulate_payment(actor=customer, tx=tx)
    return tx.contract


def test_full_signature_flow(contract, customer):
    owner = client_for(contract.owner)
    cust = client_for(customer)
    url = f"/api/v1/contracts/{contract.pk}/"
    assert cust.post(url + "send/").status_code == 403
    res = owner.post(url + "terms/", {"special_terms": "Préavis de 2 mois."}, format="json")
    assert res.data["current_version"]["number"] == 2 and "Préavis" in res.data["current_version"]["content"]
    assert owner.post(url + "send/").data["status"] == "PENDING_SIGNATURE"
    assert owner.post(url + "terms/", {"special_terms": "x"}, format="json").status_code == 409
    assert cust.post(url + "sign/", {"version_number": 1, "consent": True}, format="json").data["code"] == "stale_version"
    assert cust.post(url + "sign/", {"version_number": 2, "consent": False}, format="json").status_code == 400
    res = cust.post(url + "sign/", {"version_number": 2, "consent": True}, format="json")
    assert res.data["status"] == "PENDING_SIGNATURE" and res.data["i_signed"]
    assert cust.post(url + "sign/", {"version_number": 2, "consent": True}, format="json").status_code == 409
    res = owner.post(url + "sign/", {"version_number": 2, "consent": True}, format="json")
    assert res.data["status"] == "SIGNED" and len(res.data["signatures"]) == 2
    assert res.data["signatures"][0]["signed_sha256"] == res.data["current_version"]["content_sha256"]
    assert "qualifiée" in res.data["legal_notice"]
    dl = cust.get(url + "download/")
    assert dl.status_code == 200 and b"SHA-256" in dl.content


def test_third_party_cannot_access(contract):
    stranger = client_for(make_user())
    assert stranger.get(f"/api/v1/contracts/{contract.pk}/").status_code == 403
    assert stranger.get(f"/api/v1/contracts/{contract.pk}/download/").status_code == 403


def test_cancel_requires_reason(contract):
    c = client_for(contract.owner)
    assert c.post(f"/api/v1/contracts/{contract.pk}/cancel/", {"reason": ""}, format="json").status_code == 400
    assert c.post(f"/api/v1/contracts/{contract.pk}/cancel/", {"reason": "Désaccord"}, format="json").data["status"] == "CANCELLED"
