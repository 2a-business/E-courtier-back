"""Parcours visite confirmée → dossier locatif → transmission → examen par le responsable → décision."""

from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.applications.checks import check_required_documents
from apps.applications.models import ApplicationDocument, RentalApplication
from apps.contracts.models import Contract
from apps.moderation.models import AuditLog
from apps.notifications.models import Notification
from apps.transactions import services as tx_services
from apps.visits import services as visit_services
from conftest import client_for, fake_pdf, make_listing, make_slot, make_user

pytestmark = pytest.mark.django_db
URL = "/api/v1/applications/"
INFO = {"profession": "Comptable", "monthly_income_xof": 650000, "household_size": 2, "move_in_date": "2026-12-01"}


def book(listing, customer, confirm=True):
    visit = visit_services.book_visit(customer=customer, slot_id=make_slot(listing).pk)
    if confirm:
        visit = visit_services.change_status(actor=listing.owner, visit=visit, target="CONFIRMED")
    return visit


@pytest.fixture
def visit(listing, customer):
    return book(listing, customer)


def open_app(customer, visit):
    return client_for(customer).post(URL, {"visit": visit.pk}, format="json")


def upload(client, app_id, doc_type="ID_CARD", f=None, **extra):
    return client.post(f"{URL}{app_id}/documents/", {"doc_type": doc_type, "file": f or fake_pdf("piece"), **extra}, format="multipart")


@pytest.fixture
def ready_app(customer, visit):
    """Dossier complet, encore en brouillon."""
    c = client_for(customer)
    app_id = open_app(customer, visit).data["id"]
    assert c.patch(f"{URL}{app_id}/", INFO, format="json").status_code == 200
    assert upload(c, app_id).status_code == 201
    return app_id


@pytest.fixture
def submitted_app(customer, ready_app):
    res = client_for(customer).post(f"{URL}{ready_app}/submit/", {"consent": True}, format="json")
    assert res.status_code == 200, res.data
    return ready_app


# --- Ouverture ------------------------------------------------------------------------


def test_requires_confirmed_visit(listing, customer):
    pending = book(listing, customer, confirm=False)
    res = open_app(customer, pending)
    assert res.status_code == 400 and res.data["code"] == "visit_not_confirmed"
    assert RentalApplication.objects.count() == 0


def test_only_own_visit_and_rental_listings(listing, customer, owner):
    visit = book(listing, customer)
    assert open_app(make_user(), visit).status_code == 403
    sale = make_listing(owner, transaction_type="SALE", price=90_000_000)
    res = open_app(customer, book(sale, customer))
    assert res.status_code == 400 and res.data["code"] == "not_rental"


def test_open_is_idempotent_and_starts_incomplete(customer, visit):
    first = open_app(customer, visit)
    again = open_app(customer, visit)
    assert first.status_code == 201 and again.status_code == 200 and first.data["id"] == again.data["id"]
    data = first.data
    assert data["status"] == "DRAFT" and data["state"] == "INCOMPLETE" and data["my_role"] == "customer"
    assert data["requirements"]["missing_documents"] == ["Carte nationale d'identité ou Passeport"]
    assert data["internal_notes"] is None and data["can_edit"] is True


def test_draft_is_invisible_to_owner(listing, customer, visit):
    app_id = open_app(customer, visit).data["id"]
    owner_client = client_for(listing.owner)
    assert owner_client.get(f"{URL}{app_id}/").status_code == 403
    assert owner_client.get(f"{URL}received/").data == []


# --- Transmission ---------------------------------------------------------------------


def test_incomplete_application_cannot_be_submitted(customer, visit):
    c = client_for(customer)
    app_id = open_app(customer, visit).data["id"]
    res = c.post(f"{URL}{app_id}/submit/", {"consent": True}, format="json")
    assert res.status_code == 400 and res.data["code"] == "application_incomplete"
    assert "Carte nationale" in res.data["detail"] and "Profession" in res.data["detail"]
    assert RentalApplication.objects.get(pk=app_id).status == "DRAFT"


def test_consent_is_required(customer, ready_app):
    res = client_for(customer).post(f"{URL}{ready_app}/submit/", {"consent": False}, format="json")
    assert res.status_code == 400 and res.data["code"] == "consent_required"


def test_ready_state_then_submission_notifies_and_locks(listing, customer, ready_app):
    c = client_for(customer)
    assert c.get(f"{URL}{ready_app}/").data["state"] == "READY"
    res = c.post(f"{URL}{ready_app}/submit/", {"consent": True}, format="json")
    assert res.status_code == 200 and res.data["status"] == "SUBMITTED" and res.data["consent_accepted_at"]
    assert all(d["submitted"] for d in res.data["documents"]) and res.data["can_edit"] is False
    assert [e["event"] for e in res.data["events"]] == ["created", "submitted"]
    assert Notification.objects.filter(user=listing.owner, kind="application.submitted").count() == 1
    assert Notification.objects.filter(user=customer, kind="application.submitted").count() == 1
    # Double clic : refusé, aucune notification en double.
    again = c.post(f"{URL}{ready_app}/submit/", {"consent": True}, format="json")
    assert again.status_code == 409
    assert Notification.objects.filter(kind="application.submitted").count() == 2
    assert c.patch(f"{URL}{ready_app}/", {"profession": "Autre"}, format="json").status_code == 409


def test_cancelled_visit_blocks_submission(listing, customer, visit, ready_app):
    visit_services.change_status(actor=customer, visit=visit, target="CANCELLED")
    res = client_for(customer).post(f"{URL}{ready_app}/submit/", {"consent": True}, format="json")
    assert res.status_code == 400 and res.data["code"] == "visit_not_confirmed"


@override_settings(RENTAL_APPLICATION_REQUIRED_DOCS=[{"ID_CARD", "PASSPORT"}, {"INCOME_PROOF", "EMPLOYMENT_PROOF"}])
def test_required_documents_are_configurable(customer, ready_app):
    res = client_for(customer).post(f"{URL}{ready_app}/submit/", {"consent": True}, format="json")
    assert res.status_code == 400 and "Justificatif de revenus" in res.data["detail"]


def test_required_documents_config_check():
    assert check_required_documents() == []
    with override_settings(RENTAL_APPLICATION_REQUIRED_DOCS=[{"ID_CARD"}, {"FAUX_TYPE"}]):
        assert [e.id for e in check_required_documents()] == ["applications.E001"]


# --- Accès ----------------------------------------------------------------------------


def test_access_is_limited_to_candidate_responsible_and_admin(listing, customer, submitted_app, admin):
    other_owner = make_user("OWNER")
    make_listing(other_owner)
    assert client_for(other_owner).get(f"{URL}{submitted_app}/").status_code == 403
    assert client_for(other_owner).get(f"{URL}received/").data == []
    assert client_for(make_user()).get(f"{URL}{submitted_app}/").status_code == 403
    assert client_for(make_user()).get(URL).data == []
    owner_view = client_for(listing.owner).get(f"{URL}{submitted_app}/")
    assert owner_view.status_code == 200 and owner_view.data["my_role"] == "responsible"
    assert owner_view.data["profession"] == "Comptable" and owner_view.data["internal_notes"] == []
    received = client_for(listing.owner).get(f"{URL}received/").data
    assert [a["id"] for a in received] == [submitted_app] and received[0]["customer_name"] == customer.public_name
    admin_view = client_for(admin).get(f"{URL}{submitted_app}/")
    assert admin_view.status_code == 200 and admin_view.data["my_role"] == "admin"


def test_private_documents_access_control(listing, customer, submitted_app, admin, api):
    doc = ApplicationDocument.objects.get(application_id=submitted_app)
    url = f"{URL}documents/{doc.pk}/file/"
    assert api.get(url).status_code == 401
    assert client_for(make_user()).get(url).status_code == 403
    assert client_for(make_user("OWNER")).get(url).status_code == 403
    for user in (customer, listing.owner, admin):
        res = client_for(user).get(url)
        assert res.status_code == 200 and res["Cache-Control"] == "no-store, private"
        assert b"".join(res.streaming_content).startswith(b"%PDF")
    roles = sorted(a.metadata["role"] for a in AuditLog.objects.filter(action="application.document_viewed"))
    assert roles == ["admin", "responsible"]  # consultations tierces tracées, jamais celles du candidat
    # Stockage privé : hors MEDIA_ROOT, inaccessible par la diffusion publique.
    stored = Path(settings.PRIVATE_MEDIA_ROOT) / doc.file.name
    assert stored.is_file() and doc.file.name.startswith(f"applications/{submitted_app}/")
    assert api.get(f"/media/{doc.file.name}").status_code == 404
    assert "file" not in client_for(customer).get(f"{URL}{submitted_app}/").data["documents"][0]


def test_draft_documents_not_readable_by_owner(listing, customer, ready_app):
    doc = ApplicationDocument.objects.get(application_id=ready_app)
    assert client_for(listing.owner).get(f"{URL}documents/{doc.pk}/file/").status_code == 403


# --- Pièces ---------------------------------------------------------------------------


def test_file_type_is_checked_by_content(customer, visit):
    app_id = open_app(customer, visit).data["id"]
    fake = SimpleUploadedFile("cni.pdf", b"MZ\x90\x00executable", content_type="application/pdf")
    res = upload(client_for(customer), app_id, f=fake)
    assert res.status_code == 400 and res.data["code"] == "invalid_file_type"


def test_replace_in_draft_and_lock_after_submission(customer, ready_app, django_capture_on_commit_callbacks):
    c = client_for(customer)
    old = ApplicationDocument.objects.get(application_id=ready_app)
    name, storage = old.file.name, old.file.storage
    with django_capture_on_commit_callbacks(execute=True):
        res = upload(c, ready_app, doc_type="PASSPORT", replaces=old.pk)
    assert res.status_code == 201 and not storage.exists(name)
    assert list(ApplicationDocument.objects.filter(application_id=ready_app).values_list("doc_type", flat=True)) == ["PASSPORT"]
    c.post(f"{URL}{ready_app}/submit/", {"consent": True}, format="json")
    doc = ApplicationDocument.objects.get(application_id=ready_app)
    assert c.delete(f"{URL}documents/{doc.pk}/").status_code == 409
    assert upload(c, ready_app, replaces=doc.pk).status_code == 409


def test_only_candidate_uploads(listing, submitted_app):
    assert upload(client_for(listing.owner), submitted_app).status_code == 403


# --- Examen et décision ---------------------------------------------------------------


def test_info_request_then_resubmission(listing, customer, submitted_app):
    owner = client_for(listing.owner)
    res = owner.post(f"{URL}{submitted_app}/request-info/", {"message": " "}, format="json")
    assert res.status_code == 400
    res = owner.post(f"{URL}{submitted_app}/request-info/", {"message": "Merci d'ajouter un justificatif de revenus."}, format="json")
    assert res.status_code == 200 and res.data["status"] == "INFO_REQUESTED"
    note = Notification.objects.get(user=customer, kind="application.info_requested")
    assert "justificatif de revenus" in note.body
    c = client_for(customer)
    detail = c.get(f"{URL}{submitted_app}/").data
    assert detail["info_request_message"] == "Merci d'ajouter un justificatif de revenus." and detail["can_edit"] is True
    assert upload(c, submitted_app, doc_type="INCOME_PROOF").status_code == 201
    res = c.post(f"{URL}{submitted_app}/submit/", {"consent": True}, format="json")
    assert res.status_code == 200 and res.data["status"] == "SUBMITTED"
    assert [e["event"] for e in res.data["events"]] == ["created", "submitted", "info_requested", "resubmitted"]
    assert Notification.objects.filter(user=listing.owner, title="Complément de dossier reçu").count() == 1


def test_accept_and_reject_transitions_and_history(listing, customer, submitted_app, admin):
    owner = client_for(listing.owner)
    assert client_for(customer).post(f"{URL}{submitted_app}/decision/", {"decision": "ACCEPTED"}, format="json").status_code == 403
    assert client_for(admin).post(f"{URL}{submitted_app}/decision/", {"decision": "ACCEPTED"}, format="json").status_code == 403
    assert owner.post(f"{URL}{submitted_app}/review/").data["status"] == "UNDER_REVIEW"
    res = owner.post(f"{URL}{submitted_app}/decision/", {"decision": "REJECTED", "reason": ""}, format="json")
    assert res.status_code == 400 and res.data["code"] == "reason_required"
    res = owner.post(f"{URL}{submitted_app}/decision/", {"decision": "ACCEPTED"}, format="json")
    assert res.status_code == 200 and res.data["status"] == "ACCEPTED" and res.data["decided_at"]
    assert [e["event"] for e in res.data["events"]] == ["created", "submitted", "review_started", "accepted"]
    assert Notification.objects.filter(user=customer, kind="application.accepted").count() == 1
    again = owner.post(f"{URL}{submitted_app}/decision/", {"decision": "REJECTED", "reason": "x"}, format="json")
    assert again.status_code == 409
    assert AuditLog.objects.filter(action="application.accepted").count() == 1


def test_rejection_allows_new_application(listing, customer, visit, submitted_app):
    res = client_for(listing.owner).post(f"{URL}{submitted_app}/decision/", {"decision": "REJECTED", "reason": "Revenus insuffisants"}, format="json")
    assert res.status_code == 200 and res.data["decision_reason"] == "Revenus insuffisants"
    assert "Revenus insuffisants" in Notification.objects.get(user=customer, kind="application.rejected").body
    new = open_app(customer, visit)
    assert new.status_code == 201 and new.data["id"] != submitted_app


def test_internal_notes_hidden_from_candidate(listing, customer, submitted_app, admin):
    res = client_for(listing.owner).post(f"{URL}{submitted_app}/notes/", {"text": "Garant à vérifier"}, format="json")
    assert res.status_code == 201
    assert client_for(customer).post(f"{URL}{submitted_app}/notes/", {"text": "x"}, format="json").status_code == 403
    assert client_for(customer).get(f"{URL}{submitted_app}/").data["internal_notes"] is None
    assert [n["text"] for n in client_for(listing.owner).get(f"{URL}{submitted_app}/").data["internal_notes"]] == ["Garant à vérifier"]
    assert [n["text"] for n in client_for(admin).get(f"{URL}{submitted_app}/").data["internal_notes"]] == ["Garant à vérifier"]


# --- Paiement (lecture seule) ---------------------------------------------------------


def test_payment_not_configured_shows_no_false_confirmation(customer, listing, submitted_app):
    with override_settings(WAVE_PAYMENT_LINK=""):
        payment = client_for(customer).get(f"{URL}{submitted_app}/").data["payment"]
    assert payment == {"fee_amount": settings.DOSSIER_FEE_XOF, "currency": "XOF", "wave_configured": False, "transaction": None}
    client_for(listing.owner).post(f"{URL}{submitted_app}/decision/", {"decision": "ACCEPTED"}, format="json")
    # Accepter le dossier ne crée ni ne confirme aucun paiement.
    assert client_for(customer).get(f"{URL}{submitted_app}/").data["payment"]["transaction"] is None


def test_payment_status_follows_admin_confirmation_once(customer, listing, submitted_app, admin):
    tx, _ = tx_services.create_transaction(customer=customer, listing_id=listing.pk)
    tx_services.start_wave_payment(customer=customer, tx=tx)
    tx_services.declare_payment(customer=customer, tx=tx, provider_reference="T_DECLARE01")
    payment = client_for(listing.owner).get(f"{URL}{submitted_app}/").data["payment"]
    assert payment["transaction"]["status"] == "PENDING"  # une déclaration du client ne vaut pas paiement
    tx_services.confirm_payment(actor=admin, tx=tx, provider_reference="T_DECLARE01")
    payment = client_for(customer).get(f"{URL}{submitted_app}/").data["payment"]
    assert payment["transaction"]["status"] == "PAID" and payment["transaction"]["paid_at"]
    paid_notifications = Notification.objects.filter(kind="transaction.paid").count()
    from apps.core_errors import InvalidTransition

    with pytest.raises(InvalidTransition):
        tx_services.confirm_payment(actor=admin, tx=tx, provider_reference="T_DECLARE01")
    assert Contract.objects.filter(transaction=tx).count() == 1
    assert Notification.objects.filter(kind="transaction.paid").count() == paid_notifications
