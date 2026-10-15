from django.conf import settings
from django.db import models


class SmsStatus(models.TextChoices):
    NOT_REQUESTED = "NOT_REQUESTED", "SMS non demandé"
    NO_PHONE = "NO_PHONE", "Pas de numéro"
    LOGGED_NOT_SENT = "LOGGED_NOT_SENT", "Journalisé (aucun SMS réellement envoyé)"
    SENT = "SENT", "Envoyé au fournisseur"
    FAILED = "FAILED", "Échec"


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=50)
    title = models.CharField(max_length=140)
    body = models.TextField(max_length=1000)
    link = models.CharField(max_length=200, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    sms_status = models.CharField(max_length=20, choices=SmsStatus.choices, default=SmsStatus.NOT_REQUESTED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"])]
