from rest_framework import serializers

from apps.listings.serializers import ListingCardSerializer

from .models import DocumentType, VerificationDocument, VerificationRequest


class DocumentSerializer(serializers.ModelSerializer):
    doc_type_label = serializers.CharField(source="get_doc_type_display", read_only=True)
    submitted = serializers.SerializerMethodField()

    class Meta:
        model = VerificationDocument
        # Jamais d'URL directe vers le fichier : la lecture passe par un point d'accès contrôlé.
        fields = ["id", "doc_type", "doc_type_label", "original_name", "content_type", "size", "uploaded_at", "submitted"]

    def get_submitted(self, obj) -> bool:
        return obj.request_id is not None


class DocumentUploadSerializer(serializers.Serializer):
    doc_type = serializers.ChoiceField(choices=DocumentType.choices)
    file = serializers.FileField()


class RequestSerializer(serializers.ModelSerializer):
    documents = DocumentSerializer(many=True, read_only=True)
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = VerificationRequest
        fields = ["id", "status", "submitted_at", "decided_at", "decided_by_name", "decision_reason", "documents"]

    def get_decided_by_name(self, obj) -> str | None:
        return obj.decided_by.full_name if obj.decided_by else None


class AdminRequestSerializer(RequestSerializer):
    listing = ListingCardSerializer(read_only=True)
    submitted_by = serializers.SerializerMethodField()

    class Meta(RequestSerializer.Meta):
        fields = RequestSerializer.Meta.fields + ["listing", "submitted_by"]

    def get_submitted_by(self, obj) -> dict:
        u = obj.submitted_by
        return {"id": u.pk, "name": u.full_name, "email": u.email, "role": u.role}


class DecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
