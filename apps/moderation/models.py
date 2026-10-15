from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Journal append-only des opérations sensibles. Ne contient ni secret ni contenu de document."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=60, db_index=True)
    target_type = models.CharField(max_length=60)
    target_id = models.CharField(max_length=40)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.target_type}#{self.target_id}"


class ReportReason(models.TextChoices):
    FRAUD = "FRAUD", "Arnaque ou fraude suspectée"
    MISLEADING_PHOTOS = "MISLEADING_PHOTOS", "Photos trompeuses"
    WRONG_INFO = "WRONG_INFO", "Informations erronées (prix, surface…)"
    UNAVAILABLE = "UNAVAILABLE", "Logement plus disponible"
    ABUSIVE_FEES = "ABUSIVE_FEES", "Frais de courtage abusifs demandés"
    OTHER = "OTHER", "Autre"


class ReportStatus(models.TextChoices):
    OPEN = "OPEN", "Ouvert"
    IN_REVIEW = "IN_REVIEW", "En cours d'examen"
    RESOLVED = "RESOLVED", "Traité (mesure prise)"
    DISMISSED = "DISMISSED", "Classé sans suite"


REPORT_TRANSITIONS = {
    ReportStatus.OPEN: {ReportStatus.IN_REVIEW, ReportStatus.RESOLVED, ReportStatus.DISMISSED},
    ReportStatus.IN_REVIEW: {ReportStatus.RESOLVED, ReportStatus.DISMISSED},
    ReportStatus.RESOLVED: set(),
    ReportStatus.DISMISSED: set(),
}


class Report(models.Model):
    listing = models.ForeignKey("listings.Listing", on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports")
    reason = models.CharField(max_length=20, choices=ReportReason.choices)
    details = models.TextField(max_length=1000, blank=True)
    status = models.CharField(max_length=10, choices=ReportStatus.choices, default=ReportStatus.OPEN, db_index=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="handled_reports"
    )
    handled_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Un même utilisateur ne peut avoir qu'un signalement ouvert par annonce.
            models.UniqueConstraint(
                fields=["listing", "reporter"],
                condition=models.Q(status__in=["OPEN", "IN_REVIEW"]),
                name="unique_open_report_per_user_listing",
            )
        ]
