import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.moderation.models import AuditLog
from conftest import client_for, fake_pdf, make_user

pytestmark = pytest.mark.django_db


def upload(c, listing, doc_type, f=None):
    return c.post(f"/api/v1/verification/listings/{listing.pk}/documents/", {"doc_type": doc_type, "file": f or fake_pdf("x")}, format="multipart")


def submit_full(listing):
    c = client_for(listing.owner)
    upload(c, listing, "ID_CARD")
    upload(c, listing, "LAND_TITLE")
    res = c.post(f"/api/v1/verification/listings/{listing.pk}/submit/")
    assert res.status_code == 201
    return res.data["id"]


def test_rejects_disguised_executable(listing):
    exe = SimpleUploadedFile("titre.pdf", b"MZ\x90\x00\x03" + b"0" * 100, content_type="application/pdf")
    res = upload(client_for(listing.owner), listing, "LAND_TITLE", exe)
    assert res.status_code == 400 and res.data["code"] == "invalid_file_type"


def test_submit_requires_identity_and_property_documents(listing):
    c = client_for(listing.owner)
    upload(c, listing, "ID_CARD")
    res = c.post(f"/api/v1/verification/listings/{listing.pk}/submit/")
    assert res.status_code == 400 and res.data["code"] == "property_doc_required"


def test_full_approval_flow_shows_badge_with_disclaimer(listing, admin, api):
    req_id = submit_full(listing)
    assert api.get(f"/api/v1/listings/{listing.pk}/").data["is_verified"] is False
    queue = client_for(admin).get("/api/v1/admin/verifications/").data["results"]
    assert [r["id"] for r in queue] == [req_id]
    res = client_for(admin).post(f"/api/v1/admin/verifications/{req_id}/decision/", {"approve": True}, format="json")
    assert res.status_code == 200 and res.data["status"] == "APPROVED" and res.data["decided_by_name"]
    data = api.get(f"/api/v1/listings/{listing.pk}/").data
    assert data["is_verified"] and data["verification"]["label"] == "Annonce vérifiée"
    assert "garantie" in data["verification"]["disclaimer"]
    assert AuditLog.objects.filter(action="verification.approved").exists()
    # Décision déjà prise : impossible de rejouer.
    assert client_for(admin).post(f"/api/v1/admin/verifications/{req_id}/decision/", {"approve": False, "reason": "x"}, format="json").status_code == 409


def test_reject_requires_reason_and_allows_resubmission(listing, admin):
    req_id = submit_full(listing)
    c = client_for(admin)
    assert c.post(f"/api/v1/admin/verifications/{req_id}/decision/", {"approve": False}, format="json").status_code == 400
    assert c.post(f"/api/v1/admin/verifications/{req_id}/decision/", {"approve": False, "reason": "Titre illisible"}, format="json").status_code == 200
    listing.refresh_from_db()
    assert listing.verification_status == "REJECTED"
    submit_full(listing)


def test_only_admin_decides_and_not_on_own_listing(listing, admin):
    req_id = submit_full(listing)
    assert client_for(listing.owner).post(f"/api/v1/admin/verifications/{req_id}/decision/", {"approve": True}, format="json").status_code == 403
    # Un propriétaire devenu administrateur ne peut pas valider sa propre annonce.
    listing.owner.role = "ADMIN"
    listing.owner.save(update_fields=["role"])
    res = client_for(listing.owner).post(f"/api/v1/admin/verifications/{req_id}/decision/", {"approve": True}, format="json")
    assert res.status_code == 403


def test_document_access_control(listing, admin):
    doc_id = upload(client_for(listing.owner), listing, "ID_CARD").data["id"]
    url = f"/api/v1/verification/documents/{doc_id}/file/"
    assert client_for(make_user()).get(url).status_code == 403
    res = client_for(listing.owner).get(url)
    assert res.status_code == 200 and res["Cache-Control"] == "no-store, private"
    assert b"".join(res.streaming_content).startswith(b"%PDF")
    assert client_for(admin).get(url).status_code == 200
    assert AuditLog.objects.filter(action="verification.document_viewed").count() == 1
    # Le serializer n'expose jamais de chemin ni d'URL de fichier.
    docs = client_for(listing.owner).get(f"/api/v1/verification/listings/{listing.pk}/documents/").data
    assert "file" not in docs[0]


def test_sensitive_change_invalidates_verification(listing, admin):
    req_id = submit_full(listing)
    client_for(admin).post(f"/api/v1/admin/verifications/{req_id}/decision/", {"approve": True}, format="json")
    c = client_for(listing.owner)
    c.patch(f"/api/v1/listings/{listing.pk}/", {"price": 260000}, format="json")
    listing.refresh_from_db()
    assert listing.verification_status == "APPROVED"  # le prix n'invalide pas
    c.patch(f"/api/v1/listings/{listing.pk}/", {"district": "Mermoz"}, format="json")
    listing.refresh_from_db()
    assert listing.verification_status == "NOT_SUBMITTED"


def test_verification_status_not_writable_by_owner(listing):
    client_for(listing.owner).patch(f"/api/v1/listings/{listing.pk}/", {"verification_status": "APPROVED"}, format="json")
    listing.refresh_from_db()
    assert listing.verification_status == "NOT_SUBMITTED"
