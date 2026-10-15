"""Cycle de vérification : NOT_SUBMITTED → PENDING → APPROVED | REJECTED (→ PENDING après correction)."""

from django.db import transaction
from django.utils import timezone

from apps.core_errors import BusinessError, Forbidden, InvalidTransition
from apps.listings.models import Listing, VerificationStatus
from apps.listings.services import ensure_can_manage
from apps.moderation.services import log_action
from apps.notifications.services import notify

from . import files
from .models import IDENTITY_TYPES, PROPERTY_TYPES, RequestStatus, VerificationDocument, VerificationRequest

MAX_DOCUMENTS_PENDING = 10


@transaction.atomic
def upload_document(*, actor, listing: Listing, doc_type: str, uploaded) -> VerificationDocument:
    ensure_can_manage(actor, listing)
    if listing.verification_status == VerificationStatus.PENDING:
        raise BusinessError("Une vérification est en cours : attendez la décision avant d'ajouter des pièces.")
    if listing.verification_documents.filter(request__isnull=True).count() >= MAX_DOCUMENTS_PENDING:
        raise BusinessError(f"Maximum {MAX_DOCUMENTS_PENDING} justificatifs par demande.")
    content_type, sha256, size = files.sniff(uploaded)
    doc = VerificationDocument(
        listing=listing, doc_type=doc_type, original_name=files.safe_name(uploaded.name),
        content_type=content_type, size=size, sha256=sha256, uploaded_by=actor,
    )
    doc.file.save("document", uploaded, save=False)
    doc.save()
    log_action(actor=actor, action="verification.document_uploaded", target=doc, metadata={"doc_type": doc_type})
    return doc


@transaction.atomic
def delete_document(*, actor, document: VerificationDocument) -> None:
    ensure_can_manage(actor, document.listing)
    if document.request_id:
        raise BusinessError("Un justificatif déjà soumis ne peut plus être supprimé.")
    document.file.delete(save=False)
    document.delete()


@transaction.atomic
def submit(*, actor, listing: Listing) -> VerificationRequest:
    ensure_can_manage(actor, listing)
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    if listing.verification_status not in (VerificationStatus.NOT_SUBMITTED, VerificationStatus.REJECTED):
        raise InvalidTransition("Cette annonce est déjà en cours de vérification ou vérifiée.")
    docs = list(listing.verification_documents.filter(request__isnull=True))
    types = {d.doc_type for d in docs}
    if not types & IDENTITY_TYPES:
        raise BusinessError("Ajoutez une pièce d'identité (CNI ou passeport).", code="identity_required")
    if not types & PROPERTY_TYPES:
        raise BusinessError("Ajoutez un justificatif du bien (titre foncier, acte ou mandat).", code="property_doc_required")
    request = VerificationRequest.objects.create(listing=listing, submitted_by=actor)
    VerificationDocument.objects.filter(pk__in=[d.pk for d in docs]).update(request=request)
    listing.verification_status = VerificationStatus.PENDING
    listing.save(update_fields=["verification_status", "updated_at"])
    log_action(actor=actor, action="verification.submitted", target=request, metadata={"listing": str(listing.pk)})
    return request


@transaction.atomic
def decide(*, actor, request: VerificationRequest, approve: bool, reason: str = "") -> VerificationRequest:
    if not actor.is_admin:
        raise Forbidden("Seul un administrateur peut statuer sur une vérification.")
    request = VerificationRequest.objects.select_for_update().select_related("listing").get(pk=request.pk)
    listing = Listing.objects.select_for_update().get(pk=request.listing_id)
    if request.status != RequestStatus.PENDING:
        raise InvalidTransition("Cette demande a déjà été traitée.")
    if listing.owner_id == actor.pk:
        raise Forbidden("Un administrateur ne peut pas valider sa propre annonce.")
    if not approve and not reason.strip():
        raise BusinessError("Le motif du rejet est obligatoire.", code="reason_required")

    request.status = RequestStatus.APPROVED if approve else RequestStatus.REJECTED
    request.decided_by = actor
    request.decided_at = timezone.now()
    request.decision_reason = reason.strip()
    request.save()
    listing.verification_status = VerificationStatus.APPROVED if approve else VerificationStatus.REJECTED
    listing.save(update_fields=["verification_status", "updated_at"])
    log_action(
        actor=actor, action="verification.approved" if approve else "verification.rejected", target=request,
        metadata={"listing": str(listing.pk), "reason": reason[:300]},
    )
    notify(
        listing.owner,
        kind="verification.decision",
        title="Annonce vérifiée" if approve else "Vérification refusée",
        body=f"« {listing.title} »" + (f" — motif : {reason[:300]}" if reason else ""),
        link="/tableau-de-bord",
        sms=True,
    )
    return request


def invalidate_verification(*, listing: Listing, reason: str) -> None:
    """Appelé quand des informations essentielles changent : le badge est retiré."""
    VerificationRequest.objects.filter(
        listing=listing, status__in=[RequestStatus.PENDING, RequestStatus.APPROVED]
    ).update(status=RequestStatus.INVALIDATED, decision_reason=reason)
    Listing.objects.filter(pk=listing.pk).update(verification_status=VerificationStatus.NOT_SUBMITTED)
    log_action(actor=None, action="verification.invalidated", target=listing, metadata={"reason": reason})


def can_read_document(user, document: VerificationDocument) -> bool:
    return bool(user and user.is_authenticated and (user.is_admin or document.listing.owner_id == user.pk))
