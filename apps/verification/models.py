import uuid

from django.conf import settings
from django.core.files.storage import storages
from django.db import models


def private_storage():
    return storages["private"]


class DocumentType(models.TextChoices):
    ID_CARD = "ID_CARD", "Carte nationale d'identité"
    PASSPORT = "PASSPORT", "Passeport"
    LAND_TITLE = "LAND_TITLE", "Titre foncier"
    DEED = "DEED", "Acte de vente / bail / délibération"
    MANDATE = "MANDATE", "Mandat de gestion (agent)"
    UTILITY_BILL = "UTILITY_BILL", "Facture (Senelec, SDE…)"
    OTHER = "OTHER", "Autre justificatif"


IDENTITY_TYPES = {DocumentType.ID_CARD, DocumentType.PASSPORT}
PROPERTY_TYPES = {DocumentType.LAND_TITLE, DocumentType.DEED, DocumentType.MANDATE}


class RequestStatus(models.TextChoices):
    PENDING = "PENDING", "En attente"
    APPROVED = "APPROVED", "Approuvée"
    REJECTED = "REJECTED", "Rejetée"
    INVALIDATED = "INVALIDATED", "Invalidée (annonce modifiée)"


class VerificationRequest(models.Model):
    listing = models.ForeignKey("listings.Listing", on_delete=models.CASCADE, related_name="verification_requests")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=12, choices=RequestStatus.choices, default=RequestStatus.PENDING, db_index=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="verification_decisions"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(max_length=1000, blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["listing"], condition=models.Q(status="PENDING"), name="one_pending_verification_per_listing"
            ),
            models.CheckConstraint(
                condition=models.Q(status="PENDING") | models.Q(status="INVALIDATED") | models.Q(decided_at__isnull=False),
                name="decision_has_date",
            ),
        ]


def document_path(instance, filename):
    return f"verification/{instance.listing_id}/{uuid.uuid4().hex}"


class VerificationDocument(models.Model):
    listing = models.ForeignKey("listings.Listing", on_delete=models.CASCADE, related_name="verification_documents")
    request = models.ForeignKey(
        VerificationRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    doc_type = models.CharField(max_length=14, choices=DocumentType.choices)
    file = models.FileField(upload_to=document_path, storage=private_storage)
    original_name = models.CharField(max_length=120)
    content_type = models.CharField(max_length=40)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
