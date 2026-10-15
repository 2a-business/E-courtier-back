from rest_framework import serializers

from apps.listings.serializers import ListingCardSerializer

from .models import PaymentAttempt, Transaction, TransactionEvent, TransactionStatus


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransactionEvent
        fields = ["event", "from_status", "to_status", "note", "created_at"]


class AttemptSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PaymentAttempt
        fields = ["id", "provider", "status", "status_label", "provider_reference", "is_simulated", "created_at", "declared_at", "confirmed_at"]


class TransactionSerializer(serializers.ModelSerializer):
    listing = ListingCardSerializer(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    amount_kind_label = serializers.CharField(source="get_amount_kind_display", read_only=True)
    provider_label = serializers.CharField(source="get_provider_display", read_only=True)
    total_amount = serializers.IntegerField(read_only=True)
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    contract = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            "id", "reference", "listing", "amount", "amount_kind", "amount_kind_label", "fee_amount", "total_amount",
            "currency", "status", "status_label", "provider", "provider_label", "is_simulated", "customer_name",
            "paid_at", "created_at", "contract",
        ]

    def get_contract(self, obj) -> dict | None:
        contract = getattr(obj, "contract", None)
        if not contract:
            return None
        return {"id": contract.pk, "status": contract.status, "status_label": contract.get_status_display()}


class TransactionDetailSerializer(TransactionSerializer):
    events = EventSerializer(many=True, read_only=True)
    attempts = AttemptSerializer(many=True, read_only=True)

    class Meta(TransactionSerializer.Meta):
        fields = TransactionSerializer.Meta.fields + ["events", "attempts"]


class CreateTransactionSerializer(serializers.Serializer):
    listing = serializers.UUIDField()


class DeclareSerializer(serializers.Serializer):
    provider_reference = serializers.RegexField(r"^[A-Za-z0-9_\-]{6,64}$", error_messages={"invalid": "Référence Wave invalide."})


class TransactionCancelSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class AdminConfirmSerializer(serializers.Serializer):
    provider_reference = serializers.RegexField(r"^[A-Za-z0-9_\-]{6,64}$")
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class AdminStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[TransactionStatus.FAILED, TransactionStatus.CANCELLED, TransactionStatus.REFUNDED])
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
