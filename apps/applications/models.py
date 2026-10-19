"""Dossier locatif d'un candidat, constitué après une visite confirmée et transmis au responsable du logement.

Le responsable est toujours le propriétaire ou l'agent titulaire de l'annonce (``listing.owner``), évalué à
chaque accès : aucune valeur fournie par le client n'est utilisée pour l'autorisation.
Le dossier locatif est indépendant du paiement (Transaction) : il n'en modifie jamais le statut.
"""

import uuid

from django.conf import settings
from django.core.files.storage import storages
from django.db import models
from django.db.models import Q


def private_storage():
    return storages["private"]


class ApplicationStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    SUBMITTED = "SUBMITTED", "Transmis"
    UNDER_REVIEW = "UNDER_REVIEW", "En cours d'examen"
    INFO_REQUESTED = "INFO_REQUESTED", "Complément demandé"
    ACCEPTED = "ACCEPTED", "Accepté"
    REJECTED = "REJECTED", "Refusé"


# Statuts dans lesquels le candidat peut modifier ses informations et ses pièces.
EDITABLE_STATUSES = (ApplicationStatus.DRAFT, ApplicationStatus.INFO_REQUESTED)


class RentalApplication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    listing = models.ForeignKey("listings.Listing", on_delete=models.PROTECT, related_name="applications")
    visit = models.ForeignKey("visits.Visit", on_delete=models.PROTECT, related_name="applications")
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="rental_applications")
    status = models.CharField(max_length=16, choices=ApplicationStatus.choices, default=ApplicationStatus.DRAFT, db_index=True)

    # Informations du candidat (visibles par le responsable après transmission).
    profession = models.CharField(max_length=100, blank=True)
    employer = models.CharField(max_length=120, blank=True)
    monthly_income_xof = models.PositiveBigIntegerField(null=True, blank=True)
    household_size = models.PositiveSmallIntegerField(null=True, blank=True)
    move_in_date = models.DateField(null=True, blank=True)
    has_guarantor = models.BooleanField(default=False)
    guarantor_name = models.CharField(max_length=120, blank=True)
    message = models.TextField(max_length=1000, blank=True)

    consent_accepted_at = models.DateTimeField(null=True, blank=True)
    first_submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    info_request_message = models.TextField(max_length=1000, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    decision_reason = models.TextField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            # Un seul dossier en cours par candidat et par logement ; un nouveau dossier reste possible après un refus.
            models.UniqueConstraint(
                fields=["listing", "customer"], condition=~Q(status="REJECTED"), name="one_open_application_per_listing"
            ),
            models.CheckConstraint(
                condition=~Q(status__in=["ACCEPTED", "REJECTED"]) | Q(decided_at__isnull=False),
                name="application_decision_has_date",
            ),
            models.CheckConstraint(
                condition=Q(status="DRAFT") | Q(submitted_at__isnull=False, consent_accepted_at__isnull=False),
                name="application_submitted_has_consent",
            ),
        ]

    def __str__(self):
        return f"Dossier {self.pk} ({self.status})"


class ApplicationDocumentType(models.TextChoices):
    ID_CARD = "ID_CARD", "Carte nationale d'identité"
    PASSPORT = "PASSPORT", "Passeport"
    INCOME_PROOF = "INCOME_PROOF", "Justificatif de revenus (bulletins de salaire…)"
    EMPLOYMENT_PROOF = "EMPLOYMENT_PROOF", "Attestation de travail ou d'activité"
    RESIDENCE_PROOF = "RESIDENCE_PROOF", "Justificatif de domicile actuel"
    GUARANTOR_ID = "GUARANTOR_ID", "Pièce d'identité du garant"
    OTHER = "OTHER", "Autre document"


def application_document_path(instance, filename):
    # Stockage privé (PRIVATE_MEDIA_ROOT) : jamais sous MEDIA_ROOT/listings, jamais d'URL publique.
    return f"applications/{instance.application_id}/{uuid.uuid4().hex}"


class ApplicationDocument(models.Model):
    application = models.ForeignKey(RentalApplication, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=20, choices=ApplicationDocumentType.choices)
    file = models.FileField(upload_to=application_document_path, storage=private_storage)
    original_name = models.CharField(max_length=120)
    content_type = models.CharField(max_length=40)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    # Renseigné à la transmission : une pièce transmise n'est plus modifiable (trace de ce qui a été examiné).
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["uploaded_at", "id"]


class ApplicationEvent(models.Model):
    """Historique visible du candidat et du responsable (transmission, compléments, décisions)."""

    application = models.ForeignKey(RentalApplication, on_delete=models.CASCADE, related_name="events")
    event = models.CharField(max_length=30)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, blank=True)
    note = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ApplicationNote(models.Model):
    """Note interne du responsable : jamais visible du candidat."""

    application = models.ForeignKey(RentalApplication, on_delete=models.CASCADE, related_name="internal_notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    text = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
