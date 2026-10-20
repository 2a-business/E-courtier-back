"""Dossier locatif : constitution par le candidat, transmission, examen par le responsable du logement.

Cycle : DRAFT → SUBMITTED → (UNDER_REVIEW) → INFO_REQUESTED → SUBMITTED … → ACCEPTED | REJECTED.
Règles :
- un dossier ne s'ouvre qu'à partir d'une visite confirmée (ou effectuée) d'un logement en location ;
- la transmission exige les pièces obligatoires (RENTAL_APPLICATION_REQUIRED_DOCS), les informations requises,
  l'acceptation explicite de la clause de confidentialité et une visite non annulée ;
- seul le responsable du logement (listing.owner : propriétaire ou agent) examine et décide ; un administrateur
  peut consulter en lecture seule, chaque consultation de pièce étant journalisée ;
- le dossier ne modifie jamais le paiement : l'état de la Transaction est seulement affiché.
"""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core_errors import BusinessError, Forbidden, InvalidTransition
from apps.listings.models import TransactionType
from apps.media.files import delete_after_commit
from apps.moderation.services import log_action
from apps.notifications.services import notify
from apps.transactions import providers as wave
from apps.transactions.models import PaymentAttempt, Provider, Transaction, TransactionStatus
from apps.verification import files
from apps.visits.models import Visit, VisitStatus

from .models import (
    EDITABLE_STATUSES,
    ApplicationDocument,
    ApplicationFeePayment,
    ApplicationDocumentType,
    ApplicationEvent,
    ApplicationNote,
    ApplicationStatus,
    FeePaymentStatus,
    RentalApplication,
)

S = ApplicationStatus
TRANSITIONS = {
    S.DRAFT: {S.SUBMITTED},
    S.SUBMITTED: {S.UNDER_REVIEW, S.INFO_REQUESTED, S.ACCEPTED, S.REJECTED},
    S.UNDER_REVIEW: {S.INFO_REQUESTED, S.ACCEPTED, S.REJECTED},
    S.INFO_REQUESTED: {S.SUBMITTED, S.REJECTED},
    S.ACCEPTED: set(),
    S.REJECTED: set(),
}
VISIT_OK = (VisitStatus.CONFIRMED, VisitStatus.COMPLETED)
REQUIRED_FIELDS = {
    "profession": "Profession",
    "monthly_income_xof": "Revenus mensuels",
    "household_size": "Nombre d'occupants",
    "move_in_date": "Date d'entrée souhaitée",
}
INFO_FIELDS = ("profession", "employer", "monthly_income_xof", "household_size", "move_in_date", "has_guarantor", "guarantor_name", "message")


# --- Autorisations (toujours calculées côté serveur) ---------------------------------


def is_customer(user, app: RentalApplication) -> bool:
    return bool(user and user.is_authenticated and app.customer_id == user.pk)


def is_responsible(user, app: RentalApplication) -> bool:
    """Propriétaire ou agent titulaire de l'annonce, au moment de la requête."""
    return bool(user and user.is_authenticated and app.listing.owner_id == user.pk)


def role_for(user, app: RentalApplication) -> str | None:
    """« customer », « responsible », « admin » ou None. Un brouillon n'est visible que du candidat."""
    if is_customer(user, app):
        return "customer"
    if app.status == S.DRAFT:
        return None
    if is_responsible(user, app):
        return "responsible"
    if user and user.is_authenticated and user.is_admin:
        return "admin"
    return None


def ensure_role(user, app: RentalApplication, *allowed: str) -> str:
    role = role_for(user, app)
    if role is None or (allowed and role not in allowed):
        raise Forbidden("Ce dossier ne vous concerne pas.")
    return role


# --- Complétude ----------------------------------------------------------------------


def requirements(app: RentalApplication) -> dict:
    """Pièces obligatoires/facultatives et informations manquantes, calculées côté serveur."""
    present = {d.doc_type for d in app.documents.all()}
    labels = dict(ApplicationDocumentType.choices)
    required = []
    for group in settings.RENTAL_APPLICATION_REQUIRED_DOCS:
        types = [t for t in ApplicationDocumentType.values if t in group]
        required.append({"types": types, "label": " ou ".join(labels[t] for t in types), "satisfied": bool(present & set(types))})
    required_types = set().union(*settings.RENTAL_APPLICATION_REQUIRED_DOCS) if settings.RENTAL_APPLICATION_REQUIRED_DOCS else set()
    optional = [{"type": t, "label": labels[t], "provided": t in present} for t in ApplicationDocumentType.values if t not in required_types]
    missing_fields = [label for field, label in REQUIRED_FIELDS.items() if getattr(app, field) in (None, "")]
    if app.has_guarantor and not app.guarantor_name.strip():
        missing_fields.append("Nom du garant")
    missing_documents = [r["label"] for r in required if not r["satisfied"]]
    return {
        "required_documents": required,
        "optional_documents": optional,
        "missing_documents": missing_documents,
        "missing_fields": missing_fields,
        "is_complete": not missing_documents and not missing_fields,
        "accepted_formats": ["PDF", "JPEG", "PNG"],
        "max_document_size_mb": settings.MAX_DOCUMENT_SIZE_MB,
    }


def display_state(app: RentalApplication, reqs: dict | None = None) -> str:
    """État affiché : distingue un brouillon incomplet d'un brouillon prêt à transmettre."""
    if app.status == S.DRAFT:
        return "READY" if (reqs or requirements(app))["is_complete"] else "INCOMPLETE"
    return app.status


def fee_summary(app: RentalApplication) -> dict:
    """État réel des frais de dossier (jamais déduit d'un clic, d'un retour de Wave ou d'une déclaration)."""
    fee = getattr(app, "fee_payment", None) if app.pk else None
    amount = fee.amount if fee else settings.DOSSIER_FEE_XOF
    if amount <= 0:
        return {"status": "NOT_REQUIRED", "status_label": "Aucun frais de dossier", "amount": 0, "currency": "XOF",
                "reference": None, "provider_reference": "", "declared_at": None, "confirmed_at": None,
                "failure_reason": "", "can_pay": False, "payment_problem": None, "started": False}
    problem = wave.link_problem(wave.dossier_fee_link(), amount)
    status = fee.status if fee else "NOT_STARTED"
    payable_app = app.status in (S.SUBMITTED, S.UNDER_REVIEW, S.INFO_REQUESTED)
    payable_fee = status in (FeePaymentStatus.PENDING, FeePaymentStatus.AWAITING_VERIFICATION, FeePaymentStatus.FAILED)
    return {
        "status": status,
        "status_label": fee.get_status_display() if fee else "Dû après la transmission du dossier",
        "amount": amount, "currency": "XOF",
        "reference": fee.reference if fee else None,
        "provider_reference": fee.provider_reference if fee else "",
        "declared_at": fee.declared_at if fee else None,
        "confirmed_at": fee.confirmed_at if fee else None,
        "failure_reason": fee.failure_reason if fee else "",
        "started": bool(fee and fee.checkout_started_at),
        "can_pay": payable_app and payable_fee and problem is None,
        "payment_problem": problem if payable_app and payable_fee else None,
    }


def payment_summary(app: RentalApplication) -> dict:
    """Frais de dossier (payés via le dossier) et paiement du premier loyer (Transaction), en lecture seule."""
    tx = (
        Transaction.objects.filter(listing_id=app.listing_id, customer_id=app.customer_id)
        .exclude(status=TransactionStatus.CANCELLED)
        .order_by("-created_at")
        .first()
    )
    fee = fee_summary(app)
    return {
        "fee_amount": fee["amount"],
        "currency": "XOF",
        "wave_configured": bool(settings.WAVE_PAYMENT_LINK),
        "fee": fee,
        "transaction": None if tx is None else {
            "id": str(tx.pk), "reference": tx.reference, "status": tx.status, "status_label": tx.get_status_display(),
            "total_amount": tx.total_amount, "fee_amount": tx.fee_amount, "is_simulated": tx.is_simulated,
            "paid_at": tx.paid_at,
        },
    }


# --- Candidat -------------------------------------------------------------------------


def _event(app, event, actor=None, from_status="", to_status="", note=""):
    ApplicationEvent.objects.create(
        application=app, event=event, actor=actor, from_status=from_status, to_status=to_status, note=note[:1000]
    )


def open_for_visit(*, customer, visit_id: int) -> tuple[RentalApplication, bool]:
    """Crée ou retourne le dossier en cours du candidat pour le logement de cette visite (idempotent)."""
    try:
        visit = Visit.objects.select_related("listing").get(pk=visit_id)
    except Visit.DoesNotExist:
        raise BusinessError("Visite introuvable.", code="visit_not_found", http_status=404)
    if visit.customer_id != customer.pk:
        raise Forbidden("Cette visite ne vous concerne pas.")
    if visit.status not in VISIT_OK:
        raise BusinessError(
            "Le dossier locatif s'ouvre après la confirmation de la visite par le propriétaire ou l'agent.",
            code="visit_not_confirmed",
        )
    if visit.listing.transaction_type != TransactionType.RENT:
        raise BusinessError("Le dossier locatif concerne uniquement les logements en location.", code="not_rental")
    existing = RentalApplication.objects.filter(listing=visit.listing, customer=customer).exclude(status=S.REJECTED).first()
    if existing:
        return existing, False
    try:
        with transaction.atomic():
            app = RentalApplication.objects.create(listing=visit.listing, visit=visit, customer=customer)
            _event(app, "created", actor=customer, to_status=S.DRAFT)
    except IntegrityError:
        # Double clic : la contrainte d'unicité a protégé ; on renvoie le dossier créé par l'autre requête.
        return RentalApplication.objects.filter(listing=visit.listing, customer=customer).exclude(status=S.REJECTED).get(), False
    return app, True


def _ensure_editable(app: RentalApplication):
    if app.status not in EDITABLE_STATUSES:
        raise InvalidTransition("Ce dossier n'est plus modifiable.")


@transaction.atomic
def update_info(*, actor, app: RentalApplication, **data) -> RentalApplication:
    app = RentalApplication.objects.select_for_update().get(pk=app.pk)
    ensure_role(actor, app, "customer")
    _ensure_editable(app)
    for field in INFO_FIELDS:
        if field in data:
            setattr(app, field, data[field])
    if not app.has_guarantor:
        app.guarantor_name = ""
    app.save()
    return app


@transaction.atomic
def upload_document(*, actor, app: RentalApplication, doc_type: str, uploaded, replaces: int | None = None) -> ApplicationDocument:
    app = RentalApplication.objects.select_for_update().get(pk=app.pk)
    ensure_role(actor, app, "customer")
    _ensure_editable(app)
    old = None
    if replaces is not None:
        old = app.documents.filter(pk=replaces).first()
        if old is None:
            raise BusinessError("Pièce à remplacer introuvable.", code="document_not_found", http_status=404)
        if old.submitted_at:
            raise InvalidTransition("Une pièce déjà transmise ne peut pas être remplacée : ajoutez une nouvelle pièce.")
    elif app.documents.count() >= settings.MAX_APPLICATION_DOCUMENTS:
        raise BusinessError(f"Maximum {settings.MAX_APPLICATION_DOCUMENTS} pièces par dossier.")
    content_type, sha256, size = files.sniff(uploaded)  # type réel par signature, taille maximale
    doc = ApplicationDocument(
        application=app, doc_type=doc_type, original_name=files.safe_name(uploaded.name),
        content_type=content_type, size=size, sha256=sha256, uploaded_by=actor,
    )
    doc.file.save("document", uploaded, save=False)
    doc.save()
    if old is not None:
        delete_after_commit(old.file)
        old.delete()
    app.save(update_fields=["updated_at"])
    return doc


@transaction.atomic
def delete_document(*, actor, document: ApplicationDocument) -> None:
    app = RentalApplication.objects.select_for_update().get(pk=document.application_id)
    ensure_role(actor, app, "customer")
    _ensure_editable(app)
    if document.submitted_at:
        raise InvalidTransition("Une pièce déjà transmise ne peut pas être supprimée.")
    delete_after_commit(document.file)
    document.delete()


@transaction.atomic
def submit(*, actor, app: RentalApplication, consent: bool) -> RentalApplication:
    app = RentalApplication.objects.select_for_update().select_related("listing", "visit", "customer", "listing__owner").get(pk=app.pk)
    ensure_role(actor, app, "customer")
    if S.SUBMITTED not in TRANSITIONS[S(app.status)]:
        raise InvalidTransition("Ce dossier a déjà été transmis.")
    if app.visit.status not in VISIT_OK:
        raise BusinessError("La visite liée à ce dossier a été annulée : le dossier ne peut pas être transmis.", code="visit_not_confirmed")
    if not consent:
        raise BusinessError("Vous devez accepter la clause de confidentialité avant la transmission.", code="consent_required")
    reqs = requirements(app)
    if not reqs["is_complete"]:
        missing = reqs["missing_documents"] + reqs["missing_fields"]
        raise BusinessError(f"Dossier incomplet : {', '.join(missing)}.", code="application_incomplete")
    now = timezone.now()
    previous = app.status
    resubmission = previous == S.INFO_REQUESTED
    app.status = S.SUBMITTED
    app.consent_accepted_at = now
    app.submitted_at = now
    app.first_submitted_at = app.first_submitted_at or now
    app.save()
    app.documents.filter(submitted_at__isnull=True).update(submitted_at=now)
    if settings.DOSSIER_FEE_XOF > 0:
        # Montant figé côté serveur à la première transmission ; jamais fourni par le client.
        ApplicationFeePayment.objects.get_or_create(application=app, defaults={"amount": settings.DOSSIER_FEE_XOF})
    _event(app, "resubmitted" if resubmission else "submitted", actor=actor, from_status=previous, to_status=S.SUBMITTED)
    log_action(actor=actor, action="application.submitted", target=app, metadata={"listing": str(app.listing_id)})
    title = app.listing.title
    notify(
        app.listing.owner, kind="application.submitted",
        title="Complément de dossier reçu" if resubmission else "Nouveau dossier locatif reçu",
        body=f"{app.customer.public_name} a transmis son dossier pour « {title} ».",
        link=f"/dossiers/{app.pk}",
    )
    notify(
        app.customer, kind="application.submitted", title="Dossier transmis",
        body=f"Votre dossier pour « {title} » a été transmis au propriétaire ou à l'agent.", link=f"/dossiers/{app.pk}",
    )
    return app


# --- Responsable du logement ----------------------------------------------------------


def _transition(app, target) -> str:
    """Applique la transition (sans sauvegarder) et retourne le statut précédent."""
    if target not in TRANSITIONS[S(app.status)]:
        raise InvalidTransition(f"Action impossible sur un dossier « {app.get_status_display()} ».")
    previous = app.status
    app.status = target
    return previous


@transaction.atomic
def start_review(*, actor, app: RentalApplication) -> RentalApplication:
    app = RentalApplication.objects.select_for_update().select_related("listing", "customer").get(pk=app.pk)
    ensure_role(actor, app, "responsible")
    previous = _transition(app, S.UNDER_REVIEW)
    app.save(update_fields=["status", "updated_at"])
    _event(app, "review_started", actor=actor, from_status=previous, to_status=app.status)
    notify(app.customer, kind="application.under_review", title="Dossier en cours d'examen",
           body=f"Votre dossier pour « {app.listing.title} » est en cours d'examen.", link=f"/dossiers/{app.pk}")
    return app


@transaction.atomic
def request_info(*, actor, app: RentalApplication, message: str) -> RentalApplication:
    app = RentalApplication.objects.select_for_update().select_related("listing", "customer").get(pk=app.pk)
    ensure_role(actor, app, "responsible")
    message = message.strip()
    if not message:
        raise BusinessError("Précisez les pièces ou informations attendues.", code="message_required")
    previous = _transition(app, S.INFO_REQUESTED)
    app.info_request_message = message[:1000]
    app.save(update_fields=["status", "info_request_message", "updated_at"])
    _event(app, "info_requested", actor=actor, from_status=previous, to_status=app.status, note=message)
    notify(app.customer, kind="application.info_requested", title="Complément demandé pour votre dossier",
           body=f"« {app.listing.title} » : {message[:300]}", link=f"/dossiers/{app.pk}")
    return app


@transaction.atomic
def decide(*, actor, app: RentalApplication, decision: str, reason: str = "") -> RentalApplication:
    app = RentalApplication.objects.select_for_update().select_related("listing", "customer").get(pk=app.pk)
    ensure_role(actor, app, "responsible")
    if decision not in (S.ACCEPTED, S.REJECTED):
        raise BusinessError("Décision invalide.")
    reason = reason.strip()
    if decision == S.REJECTED and not reason:
        raise BusinessError("Un motif est obligatoire pour refuser un dossier.", code="reason_required")
    fee = ApplicationFeePayment.objects.select_for_update().filter(application=app).first()
    if decision == S.ACCEPTED and fee is not None and fee.status != FeePaymentStatus.CONFIRMED:
        raise BusinessError(
            "Le dossier ne peut être accepté qu'après la confirmation des frais de dossier par E-Courtier.",
            code="fee_not_confirmed", http_status=409,
        )
    previous = _transition(app, decision)
    if decision == S.REJECTED and fee is not None and fee.status not in (FeePaymentStatus.CONFIRMED, FeePaymentStatus.CANCELLED):
        fee.status = FeePaymentStatus.CANCELLED
        fee.save(update_fields=["status", "updated_at"])
    app.decided_at = timezone.now()
    app.decided_by = actor
    app.decision_reason = reason[:1000]
    app.save()
    _event(app, decision.lower(), actor=actor, from_status=previous, to_status=decision, note=reason)
    log_action(actor=actor, action=f"application.{decision.lower()}", target=app, metadata={"listing": str(app.listing_id)})
    accepted = decision == S.ACCEPTED
    notify(
        app.customer, kind=f"application.{decision.lower()}",
        title="Dossier accepté" if accepted else "Dossier refusé",
        body=f"« {app.listing.title} »" + (f" — motif : {reason[:300]}" if reason else ""),
        link=f"/dossiers/{app.pk}", sms=True,
    )
    return app


@transaction.atomic
def add_note(*, actor, app: RentalApplication, text: str) -> ApplicationNote:
    ensure_role(actor, app, "responsible")
    text = text.strip()
    if not text:
        raise BusinessError("La note est vide.")
    return ApplicationNote.objects.create(application=app, author=actor, text=text[:2000])


def record_document_view(*, actor, document: ApplicationDocument, role: str) -> None:
    """Trace la consultation d'une pièce par un tiers (responsable ou administrateur), jamais son contenu."""
    if role in ("responsible", "admin"):
        log_action(actor=actor, action="application.document_viewed", target=document,
                   metadata={"application": str(document.application_id), "role": role})


# --- Frais de dossier (lien Wave Business, rapprochement manuel) ----------------------


def _fee_for_update(app: RentalApplication) -> ApplicationFeePayment:
    fee = ApplicationFeePayment.objects.select_for_update().select_related("application__listing", "application__customer").filter(application=app).first()
    if fee is None:
        raise BusinessError("Aucun frais de dossier n'est dû pour ce dossier.", code="fee_not_required", http_status=409)
    return fee


def _reference_taken(reference: str, *, exclude_fee=None) -> bool:
    """Une référence Wave ne peut justifier qu'un seul paiement, frais ou loyer."""
    fees = ApplicationFeePayment.objects.filter(provider_reference=reference)
    if exclude_fee is not None:
        fees = fees.exclude(pk=exclude_fee.pk)
    return fees.exists() or PaymentAttempt.objects.filter(provider=Provider.WAVE_LINK, provider_reference=reference).exists()


@transaction.atomic
def start_fee_payment(*, actor, app: RentalApplication) -> tuple[ApplicationFeePayment, dict]:
    app = RentalApplication.objects.select_for_update().get(pk=app.pk)
    ensure_role(actor, app, "customer")
    if app.status not in (S.SUBMITTED, S.UNDER_REVIEW, S.INFO_REQUESTED):
        raise InvalidTransition("Les frais de dossier se règlent après la transmission du dossier.")
    fee = _fee_for_update(app)
    if fee.status in (FeePaymentStatus.CONFIRMED, FeePaymentStatus.CANCELLED):
        raise InvalidTransition(f"Paiement impossible : {fee.get_status_display().lower()}.")
    checkout = wave.checkout(wave.dossier_fee_link(), amount=fee.amount, reference=fee.reference)  # 503 si lien absent/incohérent
    if fee.checkout_started_at is None:  # idempotent : un seul évènement, quel que soit le nombre de clics
        fee.checkout_started_at = timezone.now()
        fee.save(update_fields=["checkout_started_at", "updated_at"])
        _event(app, "fee_payment_started", actor=actor, note=f"Redirection vers Wave ({fee.amount} FCFA)")
    return fee, {"url": checkout.url, "instructions": checkout.instructions, "auto_confirmation": False,
                 "amount": fee.amount, "reference": fee.reference}


@transaction.atomic
def declare_fee_payment(*, actor, app: RentalApplication, provider_reference: str) -> ApplicationFeePayment:
    app = RentalApplication.objects.select_for_update().get(pk=app.pk)
    ensure_role(actor, app, "customer")
    fee = _fee_for_update(app)
    if fee.checkout_started_at is None:
        raise BusinessError("Ouvrez d'abord le paiement Wave depuis E-Courtier.", code="payment_not_started", http_status=409)
    if fee.status not in (FeePaymentStatus.PENDING, FeePaymentStatus.AWAITING_VERIFICATION, FeePaymentStatus.FAILED):
        raise InvalidTransition(f"Déclaration impossible : {fee.get_status_display().lower()}.")
    reference = provider_reference.strip().upper()
    if _reference_taken(reference, exclude_fee=fee):
        raise BusinessError("Cette référence Wave est déjà associée à un autre paiement.", code="duplicate_reference", http_status=409)
    fee.provider_reference = reference
    fee.status = FeePaymentStatus.AWAITING_VERIFICATION
    fee.declared_at = timezone.now()
    fee.failure_reason = ""
    fee.save()
    _event(app, "fee_payment_declared", actor=actor, note=f"Référence déclarée : {reference}")
    return fee


@transaction.atomic
def confirm_fee_payment(*, actor, fee: ApplicationFeePayment, provider_reference: str, note: str = "") -> ApplicationFeePayment:
    """Rapprochement manuel par un administrateur, après vérification dans Wave Business (montant et référence)."""
    if not (actor and actor.is_admin):
        raise Forbidden("Seul un administrateur peut confirmer un paiement.")
    fee = ApplicationFeePayment.objects.select_for_update().select_related("application__listing", "application__customer").get(pk=fee.pk)
    if fee.status == FeePaymentStatus.CONFIRMED:
        raise InvalidTransition("Ces frais sont déjà confirmés.")
    if fee.status == FeePaymentStatus.CANCELLED:
        raise InvalidTransition("Ces frais ont été annulés (dossier refusé).")
    reference = provider_reference.strip().upper()
    if not reference:
        raise BusinessError("La référence Wave vérifiée est obligatoire.", code="reference_required")
    if _reference_taken(reference, exclude_fee=fee):
        raise BusinessError("Cette référence Wave est déjà associée à un autre paiement.", code="duplicate_reference", http_status=409)
    fee.provider_reference = reference
    fee.status = FeePaymentStatus.CONFIRMED
    fee.confirmed_at = timezone.now()
    fee.confirmed_by = actor
    fee.failure_reason = ""
    fee.save()
    app = fee.application
    _event(app, "fee_payment_confirmed", actor=actor, note=note or f"Rapproché avec la transaction Wave {reference}")
    log_action(actor=actor, action="application.fee_confirmed", target=fee, metadata={"application": str(app.pk), "amount": fee.amount})
    for user in (app.customer, app.listing.owner):
        notify(user, kind="application.fee_confirmed", title="Frais de dossier confirmés",
               body=f"« {app.listing.title} » : frais de dossier de {fee.amount} FCFA vérifiés par E-Courtier.", link=f"/dossiers/{app.pk}")
    return fee


@transaction.atomic
def reject_fee_payment(*, actor, fee: ApplicationFeePayment, reason: str) -> ApplicationFeePayment:
    if not (actor and actor.is_admin):
        raise Forbidden("Seul un administrateur peut statuer sur un paiement.")
    fee = ApplicationFeePayment.objects.select_for_update().select_related("application__listing", "application__customer").get(pk=fee.pk)
    if fee.status != FeePaymentStatus.AWAITING_VERIFICATION:
        raise InvalidTransition("Seul un paiement en attente de vérification peut être déclaré non retrouvé.")
    reason = reason.strip()
    if not reason:
        raise BusinessError("Un motif est obligatoire.", code="reason_required")
    fee.status = FeePaymentStatus.FAILED
    fee.failure_reason = reason[:300]
    fee.save(update_fields=["status", "failure_reason", "updated_at"])
    app = fee.application
    _event(app, "fee_payment_failed", actor=actor, note=reason)
    log_action(actor=actor, action="application.fee_failed", target=fee, metadata={"application": str(app.pk)})
    notify(app.customer, kind="application.fee_failed", title="Paiement des frais non retrouvé",
           body=f"« {app.listing.title} » : {reason[:200]} Vous pouvez déclarer une autre référence Wave.", link=f"/dossiers/{app.pk}")
    return fee

