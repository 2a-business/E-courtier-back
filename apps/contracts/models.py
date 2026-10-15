import uuid

from django.conf import settings
from django.db import models


class ContractStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    PENDING_SIGNATURE = "PENDING_SIGNATURE", "En attente de signature"
    SIGNED = "SIGNED", "Signé"
    CANCELLED = "CANCELLED", "Annulé"


class Contract(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.OneToOneField("transactions.Transaction", on_delete=models.PROTECT, related_name="contract")
    listing = models.ForeignKey("listings.Listing", on_delete=models.PROTECT, related_name="contracts")
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="contracts_as_customer")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="contracts_as_owner")
    status = models.CharField(max_length=18, choices=ContractStatus.choices, default=ContractStatus.DRAFT, db_index=True)
    is_simulated = models.BooleanField(default=False)
    special_terms = models.TextField("clauses particulières", max_length=3000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def current_version(self):
        return self.versions.order_by("-number").first()


class ContractVersion(models.Model):
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    content = models.TextField()
    content_sha256 = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["number"]
        constraints = [models.UniqueConstraint(fields=["contract", "number"], name="unique_contract_version")]


class SignerRole(models.TextChoices):
    CUSTOMER = "CUSTOMER", "Client"
    OWNER = "OWNER", "Propriétaire / agent"


class ContractSignature(models.Model):
    """Signature électronique simple : consentement explicite horodaté sur l'empreinte d'une version."""

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="signatures")
    version = models.ForeignKey(ContractVersion, on_delete=models.PROTECT, related_name="signatures")
    signer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    role = models.CharField(max_length=10, choices=SignerRole.choices)
    signed_sha256 = models.CharField(max_length=64)
    consent_text = models.CharField(max_length=300)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    signed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["signed_at"]
        constraints = [models.UniqueConstraint(fields=["version", "role"], name="one_signature_per_role_per_version")]
