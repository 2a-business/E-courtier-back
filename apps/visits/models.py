from django.conf import settings
from django.db import models
from django.db.models import F, Q


class VisitSlot(models.Model):
    listing = models.ForeignKey("listings.Listing", on_delete=models.CASCADE, related_name="visit_slots")
    host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="visit_slots")
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="slot_ends_after_start"),
            models.UniqueConstraint(fields=["listing", "starts_at"], name="unique_slot_per_listing_start"),
        ]


class VisitStatus(models.TextChoices):
    PENDING = "PENDING", "En attente de confirmation"
    CONFIRMED = "CONFIRMED", "Confirmée"
    CANCELLED = "CANCELLED", "Annulée"
    COMPLETED = "COMPLETED", "Effectuée"


ACTIVE_VISIT_STATUSES = [VisitStatus.PENDING, VisitStatus.CONFIRMED]


class Visit(models.Model):
    listing = models.ForeignKey("listings.Listing", on_delete=models.PROTECT, related_name="visits")
    slot = models.ForeignKey(VisitSlot, on_delete=models.PROTECT, related_name="visits")
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="visits")
    host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="hosted_visits")
    status = models.CharField(max_length=10, choices=VisitStatus.choices, default=VisitStatus.PENDING, db_index=True)
    message = models.TextField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cancel_reason = models.CharField(max_length=300, blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Garantie en base contre la double réservation d'un même créneau.
            models.UniqueConstraint(
                fields=["slot"], condition=Q(status__in=["PENDING", "CONFIRMED"]), name="one_active_visit_per_slot"
            ),
            models.UniqueConstraint(
                fields=["listing", "customer"],
                condition=Q(status__in=["PENDING", "CONFIRMED"]),
                name="one_active_visit_per_customer_listing",
            ),
        ]
