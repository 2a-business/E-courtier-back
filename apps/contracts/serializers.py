from rest_framework import serializers

from .models import Contract, ContractSignature, ContractVersion
from .templates import DISCLAIMER


class VersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContractVersion
        fields = ["number", "content", "content_sha256", "created_at"]


class SignatureSerializer(serializers.ModelSerializer):
    signer_name = serializers.CharField(source="signer.full_name", read_only=True)
    version_number = serializers.IntegerField(source="version.number", read_only=True)

    class Meta:
        model = ContractSignature
        fields = ["role", "signer_name", "version_number", "signed_sha256", "signed_at"]


class ContractSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    reference = serializers.CharField(source="transaction.reference", read_only=True)
    transaction_id = serializers.UUIDField(source="transaction.pk", read_only=True)
    listing_title = serializers.CharField(source="listing.title", read_only=True)
    current_version = VersionSerializer(read_only=True)
    signatures = serializers.SerializerMethodField()
    my_role = serializers.SerializerMethodField()
    i_signed = serializers.SerializerMethodField()
    legal_notice = serializers.SerializerMethodField()

    class Meta:
        model = Contract
        fields = [
            "id", "reference", "transaction_id", "listing_title", "status", "status_label", "is_simulated",
            "special_terms", "current_version", "signatures", "my_role", "i_signed", "legal_notice",
            "created_at", "sent_at", "signed_at", "cancelled_at", "cancel_reason",
        ]

    def get_signatures(self, obj) -> list:
        version = obj.current_version
        return SignatureSerializer(version.signatures.all() if version else [], many=True).data

    def get_my_role(self, obj) -> str:
        user = self.context["request"].user
        if user.pk == obj.customer_id:
            return "CUSTOMER"
        if user.pk == obj.owner_id:
            return "OWNER"
        return "ADMIN"

    def get_i_signed(self, obj) -> bool:
        version = obj.current_version
        return bool(version and version.signatures.filter(signer=self.context["request"].user).exists())

    def get_legal_notice(self, obj) -> str:
        return DISCLAIMER


class TermsSerializer(serializers.Serializer):
    special_terms = serializers.CharField(max_length=3000, allow_blank=True)


class SignSerializer(serializers.Serializer):
    version_number = serializers.IntegerField(min_value=1)
    consent = serializers.BooleanField()


class ContractCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)
