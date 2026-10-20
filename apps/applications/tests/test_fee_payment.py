"""Frais de dossier (lien Wave statique, rapprochement manuel) et durcissement du dépôt de pièces.

Aucun paiement réel : le lien Wave n'est jamais appelé, seule sa forme est contrôlée.
"""

from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.applications.models import ApplicationDocument, ApplicationEvent, ApplicationFeePayment
from apps.notifications.models import Notification
from apps.transactions import services as tx_services
from conftest import client_for, fake_pdf

from .test_applications import INFO, URL, book, open_app, upload

pytestmark = pytest.mark.django_db
FEE_LINK_OK = "https://pay.wave.com/m/M_test_ecourtier/c/sn/?amount=5000"
FEE_LINK_7500 = "https://pay.wave.com/m/M_test_ecourtier/c/sn/?amount=7500"
ADMIN_FEES = "/api/v1/admin/application-fees/"


@pytest.fixture
def submitted(listing, customer):
    visit = book(listing, customer)
    c = client_for(customer)
    app_id = open_app(customer, visit).data["id"]
    c.patch(f"{URL}{app_id}/", INFO, format="json")
    upload(c, app_id)
    assert c.post(f"{URL}{app_id}/submit/", {"consent": True}, format="json").status_code == 200
    return app_id


def fee_of(app_id):
    return ApplicationFeePayment.objects.get(application_id=app_id)


def start(customer, app_id, **body):
    return client_for(customer).post(f"{URL}{app_id}/fee/start/", body, format="json")


def declare(customer, app_id, reference="T_CLIENT0001"):
    return client_for(customer).post(f"{URL}{app_id}/fee/declare/", {"provider_reference": reference}, format="json")


# --- Montant et lien -------------------------------------------------------------------


def test_fee_is_created_at_submission_with_server_amount(customer, submitted):
    fee = fee_of(submitted)
    assert fee.amount == settings.DOSSIER_FEE_XOF == 5000 and fee.status == "PENDING"
    summary = client_for(customer).get(f"{URL}{submitted}/").data["payment"]["fee"]
    assert summary["amount"] == 5000 and summary["status"] == "PENDING" and summary["reference"] == fee.reference


@override_settings(WAVE_DOSSIER_FEE_LINK=FEE_LINK_OK)
def test_start_returns_configured_link_and_ignores_client_amount(customer, submitted):
    res = start(customer, submitted, amount=1, url="https://pirate.example/pay")
    assert res.status_code == 200
    checkout = res.data["checkout"]
    assert checkout["url"] == FEE_LINK_OK and checkout["amount"] == 5000 and checkout["auto_confirmation"] is False
    assert "Le montant est déjà renseigné dans Wave" in checkout["instructions"]
    assert fee_of(submitted).amount == 5000
    # Le détail du dossier n'expose jamais le lien lui-même.
    assert "pay.wave.com" not in str(client_for(customer).get(f"{URL}{submitted}/").data)


@override_settings(WAVE_DOSSIER_FEE_LINK="", WAVE_PAYMENT_LINK=FEE_LINK_7500)
def test_link_with_wrong_fixed_amount_is_refused_explicitly(customer, submitted):
    res = start(customer, submitted)
    assert res.status_code == 503 and res.data["code"] == "payment_link_invalid"
    assert "fixé à 7 500 FCFA alors que le montant dû est de 5 000 FCFA" in res.data["detail"]
    fee = client_for(customer).get(f"{URL}{submitted}/").data["payment"]["fee"]
    assert fee["can_pay"] is False and "7 500" in fee["payment_problem"]
    assert not ApplicationEvent.objects.filter(application_id=submitted, event="fee_payment_started").exists()


@override_settings(WAVE_DOSSIER_FEE_LINK="", WAVE_PAYMENT_LINK="")
def test_missing_link_does_not_break_the_dossier(customer, submitted):
    res = start(customer, submitted)
    assert res.status_code == 503 and res.data["code"] == "payment_not_configured"
    detail = client_for(customer).get(f"{URL}{submitted}/")
    assert detail.status_code == 200 and detail.data["status"] == "SUBMITTED"


@override_settings(WAVE_DOSSIER_FEE_LINK="", WAVE_PAYMENT_LINK="https://pay.wave.com/m/M_test_ecourtier/c/sn/")
def test_link_without_fixed_amount_asks_exact_amount(customer, submitted):
    res = start(customer, submitted)
    assert res.status_code == 200 and "saisissez exactement 5 000 FCFA" in res.data["checkout"]["instructions"]


@override_settings(WAVE_DOSSIER_FEE_LINK=FEE_LINK_OK)
def test_start_is_idempotent_and_requires_transmission(customer, listing):
    c = client_for(customer)
    app_id = open_app(customer, book(listing, customer)).data["id"]
    assert start(customer, app_id).status_code == 409  # brouillon : rien à payer
    c.patch(f"{URL}{app_id}/", INFO, format="json")
    upload(c, app_id)
    c.post(f"{URL}{app_id}/submit/", {"consent": True}, format="json")
    for _ in range(3):
        assert start(customer, app_id).status_code == 200
    assert ApplicationEvent.objects.filter(application_id=app_id, event="fee_payment_started").count() == 1
    assert ApplicationFeePayment.objects.filter(application_id=app_id).count() == 1


def test_only_the_candidate_can_start_or_declare(listing, submitted, admin):
    from conftest import make_user

    for user in (listing.owner, admin, make_user()):
        assert start(user, submitted).status_code == 403
        assert declare(user, submitted).status_code == 403


# --- Déclaration et rapprochement ---------------------------------------------------------


@override_settings(WAVE_DOSSIER_FEE_LINK=FEE_LINK_OK)
def test_declaration_is_never_a_confirmation(customer, listing, submitted):
    res = declare(customer, submitted)
    assert res.status_code == 409 and res.data["code"] == "payment_not_started"
    start(customer, submitted)
    res = declare(customer, submitted)
    assert res.status_code == 200
    fee = res.data["payment"]["fee"]
    assert fee["status"] == "AWAITING_VERIFICATION" and fee["status_label"] == "Paiement en attente de vérification"
    # Aucun endpoint client ne permet de confirmer ; l'acceptation reste bloquée.
    assert client_for(customer).post(f"{ADMIN_FEES}{fee_of(submitted).pk}/confirm/", {"provider_reference": "T_CLIENT0001"}, format="json").status_code == 403
    res = client_for(listing.owner).post(f"{URL}{submitted}/decision/", {"decision": "ACCEPTED"}, format="json")
    assert res.status_code == 409 and res.data["code"] == "fee_not_confirmed"
    assert fee_of(submitted).status == "AWAITING_VERIFICATION"


@override_settings(WAVE_DOSSIER_FEE_LINK=FEE_LINK_OK)
def test_admin_confirmation_once_with_notifications(customer, listing, submitted, admin):
    start(customer, submitted)
    declare(customer, submitted)
    fee = fee_of(submitted)
    queue = client_for(admin).get(ADMIN_FEES, {"status": "AWAITING_VERIFICATION"}).data["results"]
    assert [f["id"] for f in queue] == [fee.pk] and queue[0]["amount"] == 5000
    url = f"{ADMIN_FEES}{fee.pk}/confirm/"
    res = client_for(admin).post(url, {"provider_reference": "T_CLIENT0001"}, format="json")
    assert res.status_code == 200 and res.data["status"] == "CONFIRMED"
    assert Notification.objects.filter(kind="application.fee_confirmed").count() == 2  # candidat + responsable
    again = client_for(admin).post(url, {"provider_reference": "T_CLIENT0001"}, format="json")
    assert again.status_code == 409
    assert Notification.objects.filter(kind="application.fee_confirmed").count() == 2
    assert start(customer, submitted).status_code == 409  # plus rien à payer
    res = client_for(listing.owner).post(f"{URL}{submitted}/decision/", {"decision": "ACCEPTED"}, format="json")
    assert res.status_code == 200 and res.data["status"] == "ACCEPTED"
    assert res.data["payment"]["fee"]["status"] == "CONFIRMED"


@override_settings(WAVE_DOSSIER_FEE_LINK=FEE_LINK_OK)
def test_not_found_payment_can_be_declared_again(customer, submitted, admin):
    start(customer, submitted)
    declare(customer, submitted, "T_ERREUR0001")
    fee = fee_of(submitted)
    assert client_for(admin).post(f"{ADMIN_FEES}{fee.pk}/reject/", {"reason": " "}, format="json").status_code == 400
    res = client_for(admin).post(f"{ADMIN_FEES}{fee.pk}/reject/", {"reason": "Aucune transaction de 5 000 FCFA à cette référence."}, format="json")
    assert res.status_code == 200 and res.data["status"] == "FAILED"
    assert Notification.objects.filter(user=customer, kind="application.fee_failed").count() == 1
    assert declare(customer, submitted, "T_BONNE00002").data["payment"]["fee"]["status"] == "AWAITING_VERIFICATION"


@override_settings(WAVE_DOSSIER_FEE_LINK=FEE_LINK_OK)
def test_wave_reference_cannot_justify_two_payments(customer, listing, submitted, admin, owner):
    from conftest import make_listing

    start(customer, submitted)
    declare(customer, submitted, "T_UNIQUE0001")
    # Même référence pour le paiement du loyer : refusée.
    other = make_listing(owner, title="Autre logement")
    book(other, customer)
    tx, _ = tx_services.create_transaction(customer=customer, listing_id=other.pk)
    with override_settings(WAVE_PAYMENT_LINK="https://pay.wave.com/m/M_test_ecourtier/c/sn/"):
        tx_services.start_wave_payment(customer=customer, tx=tx)
    res = client_for(customer).post(f"/api/v1/transactions/{tx.pk}/declare/", {"provider_reference": "T_UNIQUE0001"}, format="json")
    assert res.status_code == 409 and res.data["code"] == "duplicate_reference"


def test_rejected_dossier_cancels_unconfirmed_fee(listing, submitted, customer):
    res = client_for(listing.owner).post(f"{URL}{submitted}/decision/", {"decision": "REJECTED", "reason": "Dossier incomplet"}, format="json")
    assert res.status_code == 200 and res.data["payment"]["fee"]["status"] == "CANCELLED"
    assert start(customer, submitted).status_code == 409


def test_resubmission_keeps_a_single_fee(listing, customer, submitted):
    client_for(listing.owner).post(f"{URL}{submitted}/request-info/", {"message": "Ajoutez un justificatif de revenus."}, format="json")
    c = client_for(customer)
    upload(c, submitted, doc_type="INCOME_PROOF")
    assert c.post(f"{URL}{submitted}/submit/", {"consent": True}, format="json").status_code == 200
    assert ApplicationFeePayment.objects.filter(application_id=submitted).count() == 1


def test_no_fee_means_not_required_and_acceptance_allowed(listing, customer, settings):
    settings.DOSSIER_FEE_XOF = 0  # avant la transmission (un décorateur ne s'appliquerait pas aux fixtures)
    c = client_for(customer)
    submitted = open_app(customer, book(listing, customer)).data["id"]
    c.patch(f"{URL}{submitted}/", INFO, format="json")
    upload(c, submitted)
    assert c.post(f"{URL}{submitted}/submit/", {"consent": True}, format="json").status_code == 200
    assert not ApplicationFeePayment.objects.filter(application_id=submitted).exists()
    assert client_for(customer).get(f"{URL}{submitted}/").data["payment"]["fee"]["status"] == "NOT_REQUIRED"
    assert client_for(listing.owner).post(f"{URL}{submitted}/decision/", {"decision": "ACCEPTED"}, format="json").status_code == 200


def test_rent_payment_link_with_fixed_amount_is_not_used_for_rent(listing, customer):
    book(listing, customer)
    tx, _ = tx_services.create_transaction(customer=customer, listing_id=listing.pk)
    assert tx.fee_amount == 0  # frais réglés via le dossier
    with override_settings(WAVE_PAYMENT_LINK=FEE_LINK_7500):
        res = client_for(customer).post(f"/api/v1/transactions/{tx.pk}/wave/")
    assert res.status_code == 503 and res.data["code"] == "payment_link_invalid"


# --- Pièces : taille, contenu réel, noms de fichiers, persistance ----------------------


@pytest.fixture
def draft(listing, customer):
    return open_app(customer, book(listing, customer)).data["id"]


@override_settings(MAX_DOCUMENT_SIZE_MB=1)
def test_oversized_pdf_is_rejected(customer, draft):
    big = SimpleUploadedFile("dossier.pdf", b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10), content_type="application/pdf")
    res = upload(client_for(customer), draft, f=big)
    assert res.status_code == 400 and res.data["code"] == "file_too_large"


@pytest.mark.parametrize("name,content", [
    ("dossier.pdf", b"MZ\x90\x00executable"),          # exécutable renommé
    ("dossier.pdf", b"<html><script>alert(1)</script>"),  # HTML déguisé
    ("image.gif", b"GIF89a....."),                     # format non autorisé
    ("vide.pdf", b""),                                 # fichier vide
])
def test_falsified_or_forbidden_files_are_rejected(customer, draft, name, content):
    res = upload(client_for(customer), draft, f=SimpleUploadedFile(name, content, content_type="application/pdf"))
    assert res.status_code == 400
    assert not ApplicationDocument.objects.filter(application_id=draft).exists()


def test_malicious_file_name_never_reaches_the_storage_path(customer, draft):
    evil = SimpleUploadedFile("../../../etc/passwd.pdf", fake_pdf("x").read(), content_type="application/pdf")
    assert upload(client_for(customer), draft, f=evil).status_code == 201
    doc = ApplicationDocument.objects.get(application_id=draft)
    assert "/" not in doc.original_name and "\\" not in doc.original_name
    assert doc.file.name.startswith(f"applications/{draft}/") and ".." not in doc.file.name
    res = client_for(customer).get(f"{URL}documents/{doc.pk}/file/")
    assert res.status_code == 200 and "/" not in res["Content-Disposition"].split("filename=")[1]


def test_pdf_persists_in_private_storage_across_restart(customer, draft):
    """Un « redémarrage » = un nouveau stockage pointant vers le même répertoire : le fichier y est toujours."""
    assert upload(client_for(customer), draft).status_code == 201
    doc = ApplicationDocument.objects.get(application_id=draft)
    fresh = FileSystemStorage(location=str(settings.PRIVATE_MEDIA_ROOT))
    assert fresh.exists(doc.file.name) and Path(fresh.path(doc.file.name)).read_bytes().startswith(b"%PDF")
    assert Path(settings.PRIVATE_MEDIA_ROOT).resolve() != Path(settings.MEDIA_ROOT).resolve()
    assert client_for(customer).get(f"/media/{doc.file.name}").status_code == 404


def test_requirements_announce_formats_and_size(customer, draft):
    req = client_for(customer).get(f"{URL}{draft}/").data["requirements"]
    assert req["accepted_formats"] == ["PDF", "JPEG", "PNG"] and req["max_document_size_mb"] == settings.MAX_DOCUMENT_SIZE_MB


# --- Garde-fou de déploiement ------------------------------------------------------------


def test_readiness_reports_pending_migrations(api, monkeypatch):
    assert api.get("/health/ready/").json() == {"status": "ready"}
    from django.db.migrations import executor

    monkeypatch.setattr(executor.MigrationExecutor, "migration_plan", lambda self, targets: [("x", False)] * 2)
    res = api.get("/health/ready/")
    assert res.status_code == 503 and res.json() == {"status": "migrations_pending", "pending": 2}
