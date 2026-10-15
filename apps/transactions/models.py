import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class AmountKind(models.TextChoices):
    FIRST_MONTH_RENT = "FIRST_MONTH_RENT", "Premier mois de loyer"
    RESERVATION_DEPOSIT = "RESERVATION_DEPOSIT", "Acompte de réservation (achat)"


class TransactionStatus(models.TextChoices):
    PENDING = "PENDING", "En attente de paiement"
    PAID = "PAID", "Payée"
    FAILED = "FAILED", "Échouée"
    CANCELLED = "CANCELLED", "Annulée"
    REFUNDED = "REFUNDED", "Remboursée"


class Provider(models.TextChoices):
    WAVE_LINK = "WAVE_LINK", "Wave Business (lien de paiement)"
    SIMULATION = "SIMULATION", "Simulation (démonstration)"


class Transaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=20, unique=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="transactions")
    listing = models.ForeignKey("listings.Listing", on_delete=models.PROTECT, related_name="transactions")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_transactions")
    amount = models.PositiveBigIntegerField("montant lié au logement (FCFA)")
    amount_kind = models.CharField(max_length=20, choices=AmountKind.choices)
    fee_amount = models.PositiveIntegerField("frais de dossier (FCFA)")
    currency = models.CharField(max_length=3, default="XOF", editable=False)
    status = models.CharField(max_length=10, choices=TransactionStatus.choices, default=TransactionStatus.PENDING, db_index=True)
    provider = models.CharField(max_length=12, choices=Provider.choices, default=Provider.WAVE_LINK)
    is_simulated = models.BooleanField(default=False)
    idempotency_key = models.CharField(max_length=64, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "listing"], condition=Q(status="PENDING"), name="one_pending_transaction_per_customer_listing"
            ),
            models.UniqueConstraint(
                fields=["listing"], condition=Q(status="PAID"), name="one_paid_transaction_per_listing"
            ),
            models.UniqueConstraint(
                fields=["customer", "idempotency_key"], condition=~Q(idempotency_key=""), name="unique_idempotency_key"
            ),
            models.CheckConstraint(condition=Q(currency="XOF"), name="transaction_currency_xof"),
            models.CheckConstraint(condition=~Q(status="PAID") | Q(paid_at__isnull=False), name="paid_has_date"),
        ]

    @property
    def total_amount(self) -> int:
        return self.amount + self.fee_amount


class AttemptStatus(models.TextChoices):
    INITIATED = "INITIATED", "Redirigé vers le prestataire"
    CUSTOMER_DECLARED = "CUSTOMER_DECLARED", "Paiement déclaré par le client (à vérifier)"
    CONFIRMED = "CONFIRMED", "Confirmé"
    REJECTED = "REJECTED", "Non retrouvé / rejeté"


class PaymentAttempt(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="attempts")
    provider = models.CharField(max_length=12, choices=Provider.choices)
    status = models.CharField(max_length=20, choices=AttemptStatus.choices, default=AttemptStatus.INITIATED)
    checkout_url = models.URLField(blank=True)
    provider_reference = models.CharField("référence Wave", max_length=64, blank=True)
    is_simulated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    declared_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_reference"], condition=~Q(provider_reference=""),
                name="unique_provider_reference",
            )
        ]


class TransactionEvent(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="events")
    event = models.CharField(max_length=40)
    from_status = models.CharField(max_length=10, blank=True)
    to_status = models.CharField(max_length=10, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
