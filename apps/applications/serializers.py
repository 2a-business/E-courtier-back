from rest_framework import serializers

from apps.listings.serializers import ListingCardSerializer

from . import services
from .models import ApplicationDocument, ApplicationDocumentType, ApplicationEvent, ApplicationNote, RentalApplication


class ApplicationDocumentSerializer(serializers.ModelSerializer):
    doc_type_label = serializers.CharField(source="get_doc_type_display", read_only=True)
    submitted = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationDocument
        # Jamais d'URL ni de chemin de fichier : lecture via /applications/documents/<id>/file/ après contrôle d'accès.
        fields = ["id", "doc_type", "doc_type_label", "original_name", "content_type", "size", "uploaded_at", "submitted"]

    def get_submitted(self, obj) -> bool:
        return obj.submitted_at is not None


class ApplicationEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationEvent
        fields = ["event", "from_status", "to_status", "note", "actor_name", "created_at"]

    def get_actor_name(self, obj) -> str | None:
        return obj.actor.public_name if obj.actor else None


class ApplicationNoteSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationNote
        fields = ["id", "text", "author_name", "created_at"]

    def get_author_name(self, obj) -> str:
        return obj.author.public_name


class ApplicationListSerializer(serializers.ModelSerializer):
    listing = ListingCardSerializer(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    state = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = RentalApplication
        fields = ["id", "listing", "visit", "status", "status_label", "state", "customer_name", "submitted_at", "decided_at", "updated_at"]

    def get_state(self, obj) -> str:
        return services.display_state(obj)

    def get_customer_name(self, obj) -> str:
        return obj.customer.public_name


class ApplicationDetailSerializer(ApplicationListSerializer):
    documents = ApplicationDocumentSerializer(many=True, read_only=True)
    events = ApplicationEventSerializer(many=True, read_only=True)
    requirements = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()
    my_role = serializers.SerializerMethodField()
    internal_notes = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta(ApplicationListSerializer.Meta):
        fields = ApplicationListSerializer.Meta.fields + [
            "profession", "employer", "monthly_income_xof", "household_size", "move_in_date", "has_guarantor",
            "guarantor_name", "message", "consent_accepted_at", "first_submitted_at", "info_request_message",
            "decision_reason", "documents", "events", "requirements", "payment", "my_role", "internal_notes", "can_edit",
        ]

    def _role(self, obj):
        return services.role_for(self.context["request"].user, obj)

    def get_requirements(self, obj) -> dict:
        return services.requirements(obj)

    def get_state(self, obj) -> str:
        return services.display_state(obj)

    def get_payment(self, obj) -> dict:
        return services.payment_summary(obj)

    def get_my_role(self, obj) -> str | None:
        return self._role(obj)

    def get_can_edit(self, obj) -> bool:
        return self._role(obj) == "customer" and obj.status in ("DRAFT", "INFO_REQUESTED")

    def get_internal_notes(self, obj) -> list | None:
        # Notes internes : responsable et administration uniquement, jamais le candidat.
        if self._role(obj) not in ("responsible", "admin"):
            return None
        return ApplicationNoteSerializer(obj.internal_notes.select_related("author"), many=True).data


class OpenApplicationSerializer(serializers.Serializer):
    visit = serializers.IntegerField()


class ApplicationInfoSerializer(serializers.Serializer):
    profession = serializers.CharField(max_length=100, required=False, allow_blank=True)
    employer = serializers.CharField(max_length=120, required=False, allow_blank=True)
    monthly_income_xof = serializers.IntegerField(min_value=0, max_value=10_000_000_000, required=False, allow_null=True)
    household_size = serializers.IntegerField(min_value=1, max_value=30, required=False, allow_null=True)
    move_in_date = serializers.DateField(required=False, allow_null=True)
    has_guarantor = serializers.BooleanField(required=False)
    guarantor_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    message = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class ApplicationDocumentUploadSerializer(serializers.Serializer):
    doc_type = serializers.ChoiceField(choices=ApplicationDocumentType.choices)
    file = serializers.FileField()
    replaces = serializers.IntegerField(required=False, allow_null=True)


class SubmitSerializer(serializers.Serializer):
    consent = serializers.BooleanField()


class InfoRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=1000)


class ApplicationDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["ACCEPTED", "REJECTED"])
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class NoteSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=2000)
