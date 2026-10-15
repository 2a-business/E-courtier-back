import uuid

from django.conf import settings
from django.db import models


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    # Empreinte (hachée) du client anonyme : jamais l'adresse IP en clair.
    anon_key = models.CharField(max_length=64, blank=True)
    last_criteria = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=[("user", "Utilisateur"), ("assistant", "Assistant")])
    text = models.TextField(max_length=2000)
    criteria = models.JSONField(default=dict, blank=True)
    listing_ids = models.JSONField(default=list, blank=True)
    mode = models.CharField(max_length=12, blank=True)  # llm | rules | fallback
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class DailyUsage(models.Model):
    """Compteurs journaliers : scope = « global », « user:<id> » ou « anon:<hash> »."""

    date = models.DateField()
    scope = models.CharField(max_length=80)
    requests = models.PositiveIntegerField(default=0)
    llm_requests = models.PositiveIntegerField(default=0)
    provider_calls = models.PositiveIntegerField(default=0)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["date", "scope"], name="unique_usage_per_day_scope")]


class LLMCallLog(models.Model):
    """Journal technique des appels fournisseur. Ne contient aucun texte saisi par l'utilisateur."""

    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=80)
    status = models.CharField(max_length=20)  # ok | rate_limited | server_error | timeout | invalid | error
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
