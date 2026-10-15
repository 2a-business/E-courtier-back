import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.core_errors import Conflict
from apps.visits import services
from apps.visits.models import Visit, VisitSlot
from apps.notifications.models import Notification
from conftest import client_for, make_listing, make_slot, make_user

pytestmark = pytest.mark.django_db


def test_owner_creates_slots_and_public_sees_only_free_future_slots(listing, api, customer):
    day = timezone.localdate() + timedelta(days=2)
    res = client_for(listing.owner).post("/api/v1/visits/manage/slots/", {
        "listing": str(listing.pk), "date": day.isoformat(), "start_time": "09:00", "end_time": "11:00", "duration_minutes": 30,
    }, format="json")
    assert res.status_code == 201 and len(res.data) == 4
    slots = api.get("/api/v1/visits/slots/", {"listing": str(listing.pk)}).data
    assert len(slots) == 4
    assert timezone.localtime(VisitSlot.objects.order_by("starts_at").first().starts_at).hour == 9
    services.book_visit(customer=customer, slot_id=slots[0]["id"])
    assert len(api.get("/api/v1/visits/slots/", {"listing": str(listing.pk)}).data) == 3


def test_slots_must_be_in_future_and_owner_only(listing, customer):
    c = client_for(listing.owner)
    payload = {"listing": str(listing.pk), "date": (timezone.localdate() - timedelta(days=1)).isoformat(),
               "start_time": "09:00", "end_time": "10:00"}
    assert c.post("/api/v1/visits/manage/slots/", payload, format="json").status_code == 400
    payload["date"] = (timezone.localdate() + timedelta(days=3)).isoformat()
    assert client_for(customer).post("/api/v1/visits/manage/slots/", payload, format="json").status_code == 403


def test_booking_and_double_booking_blocked(listing, customer):
    slot = make_slot(listing)
    res = client_for(customer).post("/api/v1/visits/", {"slot_id": slot.pk, "message": "Bonjour"}, format="json")
    assert res.status_code == 201 and res.data["status"] == "PENDING" and res.data["address"] is None
    other = make_user()
    res = client_for(other).post("/api/v1/visits/", {"slot_id": slot.pk}, format="json")
    assert res.status_code == 409 and res.data["code"] == "slot_taken"
    assert Notification.objects.filter(user=listing.owner, kind="visit.requested", sms_status="NO_PHONE").exists()


def test_cannot_book_own_listing_or_twice_same_listing(listing, customer):
    s1, s2 = make_slot(listing, 48), make_slot(listing, 72)
    assert client_for(listing.owner).post("/api/v1/visits/", {"slot_id": s1.pk}, format="json").status_code == 403
    client_for(customer).post("/api/v1/visits/", {"slot_id": s1.pk}, format="json")
    res = client_for(customer).post("/api/v1/visits/", {"slot_id": s2.pk}, format="json")
    assert res.status_code == 409 and res.data["code"] == "already_booked"


def test_cancelled_slot_becomes_bookable_again(listing, customer):
    slot = make_slot(listing)
    visit = services.book_visit(customer=customer, slot_id=slot.pk)
    client_for(customer).post(f"/api/v1/visits/{visit.pk}/status/", {"status": "CANCELLED", "reason": "Empêchement"}, format="json")
    assert services.book_visit(customer=make_user(), slot_id=slot.pk).status == "PENDING"


def test_status_transitions_and_address_disclosure(listing, customer):
    visit = services.book_visit(customer=customer, slot_id=make_slot(listing).pk)
    c = client_for(customer)
    assert c.post(f"/api/v1/visits/{visit.pk}/status/", {"status": "CONFIRMED"}, format="json").status_code == 403
    host = client_for(listing.owner)
    res = host.post(f"/api/v1/visits/{visit.pk}/status/", {"status": "CONFIRMED"}, format="json")
    assert res.status_code == 200
    res = c.get(f"/api/v1/visits/{visit.pk}/")
    assert res.data["address"] == "Rue 10, Fann Hock"
    assert c.get(f"/api/v1/listings/{listing.pk}/").data["address_private"] == "Rue 10, Fann Hock"
    # Visite future : impossible de la marquer effectuée.
    assert host.post(f"/api/v1/visits/{visit.pk}/status/", {"status": "COMPLETED"}, format="json").status_code == 400
    assert host.post(f"/api/v1/visits/{visit.pk}/status/", {"status": "PENDING"}, format="json").status_code == 400
    assert client_for(make_user()).get(f"/api/v1/visits/{visit.pk}/").status_code == 403


def test_unpublished_listing_cannot_be_booked(owner, customer):
    listing = make_listing(owner, publish=False)
    slot = make_slot(listing)
    assert client_for(customer).post("/api/v1/visits/", {"slot_id": slot.pk}, format="json").status_code == 400


def test_reminders_sent_once(listing, customer):
    visit = services.book_visit(customer=customer, slot_id=make_slot(listing, hours_ahead=5).pk)
    services.change_status(actor=listing.owner, visit=visit, target="CONFIRMED")
    assert services.send_due_reminders() == 1
    assert services.send_due_reminders() == 0


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_concurrent_booking_only_one_wins(owner):
    if connection.vendor != "postgresql":
        pytest.skip("Test de concurrence réel : nécessite PostgreSQL (TEST_DATABASE_URL).")
    listing = make_listing(owner)
    slot = make_slot(listing)
    customers = [make_user() for _ in range(6)]
    barrier = threading.Barrier(len(customers))
    outcomes = []

    def attempt(user):
        barrier.wait()
        try:
            services.book_visit(customer=user, slot_id=slot.pk)
            outcomes.append("ok")
        except Conflict:
            outcomes.append("conflict")
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt, args=(u,)) for u in customers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") == 1 and outcomes.count("conflict") == 5
    assert Visit.objects.filter(slot=slot, status__in=["PENDING", "CONFIRMED"]).count() == 1
