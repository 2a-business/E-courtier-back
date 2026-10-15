import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.listings.models import Listing
from conftest import building, client_for, make_listing, make_user

pytestmark = pytest.mark.django_db

PAYLOAD = {
    "title": "Studio Mermoz", "description": "Calme", "property_type": "STUDIO", "transaction_type": "RENT",
    "price": 150000, "rooms": 1, "bedrooms": 0, "bathrooms": 1, "city": "Dakar", "district": "Mermoz",
    "latitude": "14.707100", "longitude": "-17.475100", "amenities": ["climatisation"],
}


def test_customer_cannot_create_listing(customer):
    assert client_for(customer).post("/api/v1/listings/", PAYLOAD, format="json").status_code == 403


def test_owner_creates_draft_then_publishes_with_photo(owner, api):
    c = client_for(owner)
    res = c.post("/api/v1/listings/", PAYLOAD, format="json")
    assert res.status_code == 201
    pk = res.data["id"]
    assert res.data["publication_status"] == "DRAFT" and res.data["currency"] == "XOF"
    assert api.get(f"/api/v1/listings/{pk}/").status_code == 404  # brouillon invisible
    res = c.post(f"/api/v1/listings/{pk}/publication/", {"status": "PUBLISHED"}, format="json")
    assert res.status_code == 400 and res.data["code"] == "photo_required"
    res = c.post(f"/api/v1/listings/{pk}/photos/", {"image": building(3)}, format="multipart")
    assert res.status_code == 201 and res.data["is_primary"]
    assert c.post(f"/api/v1/listings/{pk}/publication/", {"status": "PUBLISHED"}, format="json").data["publication_status"] == "PUBLISHED"
    assert api.get(f"/api/v1/listings/{pk}/").status_code == 200


def test_unknown_amenity_and_invalid_values_rejected(owner):
    c = client_for(owner)
    assert c.post("/api/v1/listings/", PAYLOAD | {"amenities": ["jacuzzi-volant"]}, format="json").status_code == 400
    assert c.post("/api/v1/listings/", PAYLOAD | {"price": 10}, format="json").status_code == 400
    assert c.post("/api/v1/listings/", PAYLOAD | {"latitude": "48.85", "longitude": "2.35"}, format="json").status_code == 400
    assert c.post("/api/v1/listings/", PAYLOAD | {"bedrooms": 4, "rooms": 2}, format="json").status_code == 400


def test_public_detail_hides_private_address_and_rounds_coordinates(listing, api):
    data = api.get(f"/api/v1/listings/{listing.pk}/").data
    assert data["address_private"] is None
    assert data["latitude"] == 14.686 and data["longitude"] == -17.465
    assert "email" not in data["owner"] and "phone" not in data["owner"]
    assert data["verification"]["label"] is None
    assert client_for(listing.owner).get(f"/api/v1/listings/{listing.pk}/").data["address_private"] == "Rue 10, Fann Hock"


def test_other_owner_cannot_modify(listing):
    other = make_user("OWNER")
    c = client_for(other)
    assert c.patch(f"/api/v1/listings/{listing.pk}/", {"price": 1000}, format="json").status_code == 403
    assert c.post(f"/api/v1/listings/{listing.pk}/photos/", {"image": building(2)}, format="multipart").status_code == 403


def test_photo_validation_rejects_fake_image_and_strips_exif(listing):
    c = client_for(listing.owner)
    fake = SimpleUploadedFile("x.jpg", b"MZ\x90\x00 not an image", content_type="image/jpeg")
    assert c.post(f"/api/v1/listings/{listing.pk}/photos/", {"image": fake}, format="multipart").status_code == 400
    res = c.post(f"/api/v1/listings/{listing.pk}/photos/", {"image": building(4)}, format="multipart")
    assert res.status_code == 201 and not res.data["is_primary"]
    photo = listing.photos.get(pk=res.data["id"])
    with Image.open(photo.image.path) as img:
        assert img.format == "JPEG" and max(img.size) <= 1600 and not img.getexif()


def test_delete_primary_photo_promotes_next_and_unpublishes_when_last(listing):
    c = client_for(listing.owner)
    first = listing.photos.get()
    assert c.delete(f"/api/v1/listings/{listing.pk}/photos/{first.pk}/").status_code == 204
    listing.refresh_from_db()
    assert listing.publication_status == "DRAFT"


def test_admin_moderation_suspend_blocks_owner_republish(listing, admin, api):
    res = client_for(admin).post(f"/api/v1/admin/listings/{listing.pk}/moderation/", {"action": "suspend", "reason": "Fraude"}, format="json")
    assert res.status_code == 200
    assert api.get(f"/api/v1/listings/{listing.pk}/").status_code == 404
    res = client_for(listing.owner).post(f"/api/v1/listings/{listing.pk}/publication/", {"status": "PUBLISHED"}, format="json")
    assert res.status_code == 409
    assert client_for(listing.owner).post(f"/api/v1/admin/listings/{listing.pk}/moderation/", {"action": "restore", "reason": "x"}, format="json").status_code == 403


def test_delete_only_drafts(owner):
    draft = make_listing(owner, publish=False)
    published = make_listing(owner)
    c = client_for(owner)
    assert c.delete(f"/api/v1/listings/{published.pk}/").status_code == 400
    assert c.delete(f"/api/v1/listings/{draft.pk}/").status_code == 204
    assert not Listing.objects.filter(pk=draft.pk).exists()


def test_my_listings_and_stats(listing):
    c = client_for(listing.owner)
    assert c.get("/api/v1/listings/mine/").data["count"] == 1
    stats = c.get("/api/v1/listings/mine/stats/").data
    assert stats["listings_total"] == 1 and len(stats["visit_requests_daily"]) == 30
