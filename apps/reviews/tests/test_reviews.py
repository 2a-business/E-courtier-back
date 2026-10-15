import pytest
from django.utils import timezone

from apps.visits.models import Visit
from conftest import client_for, make_user, past_slot

pytestmark = pytest.mark.django_db


def completed_visit(listing, customer):
    slot = past_slot(listing)
    return Visit.objects.create(listing=listing, slot=slot, customer=customer, host=listing.owner, status="COMPLETED", completed_at=timezone.now())


def test_review_requires_completed_visit(listing, customer, api):
    url = f"/api/v1/reviews/listings/{listing.pk}/"
    payload = {"rating": 4, "owner_rating": 5, "comment": "Bien"}
    res = client_for(customer).post(url, payload, format="json")
    assert res.status_code == 400 and res.data["code"] == "visit_required"
    completed_visit(listing, customer)
    assert client_for(customer).get(url).data["can_review"] is True
    assert client_for(customer).post(url, payload, format="json").status_code == 201
    assert client_for(customer).post(url, payload, format="json").status_code == 409
    data = api.get(url).data
    assert len(data["results"]) == 1 and data["owner_rating"]["average"] == 5
    assert api.get(f"/api/v1/listings/{listing.pk}/").data["rating"] == {"average": 4.0, "count": 1}


def test_owner_cannot_review_own_listing_and_rating_bounds(listing, customer):
    url = f"/api/v1/reviews/listings/{listing.pk}/"
    assert client_for(listing.owner).post(url, {"rating": 5, "owner_rating": 5}, format="json").status_code == 403
    completed_visit(listing, customer)
    assert client_for(customer).post(url, {"rating": 6, "owner_rating": 5}, format="json").status_code == 400


def test_admin_can_hide_review(listing, customer, admin, api):
    completed_visit(listing, customer)
    rid = client_for(customer).post(f"/api/v1/reviews/listings/{listing.pk}/", {"rating": 1, "owner_rating": 1, "comment": "Insulte"}, format="json").data["id"]
    client_for(admin).post(f"/api/v1/admin/reviews/{rid}/moderation/", {"hide": True, "note": "Propos injurieux"}, format="json")
    assert api.get(f"/api/v1/reviews/listings/{listing.pk}/").data["results"] == []
    assert client_for(make_user()).post(f"/api/v1/admin/reviews/{rid}/moderation/", {"hide": False, "note": "x"}, format="json").status_code == 403
