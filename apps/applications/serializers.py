from rest_framework import serializers

from apps.listings.serializers import ListingCardSerializer

from . import services
from .models import (
    ApplicationDocument,
    ApplicationDocumentType,
    ApplicationEvent,
    ApplicationFeePayment,
    ApplicationNote,
    RentalApplication,
)


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
    responsible = serializers.SerializerMethodField()
    visit_starts_at = serializers.DateTimeField(source="visit.slot.starts_at", read_only=True)

    class Meta(ApplicationListSerializer.Meta):
        fields = ApplicationListSerializer.Meta.fields + [
            "profession", "employer", "monthly_income_xof", "household_size", "move_in_date", "has_guarantor",
            "guarantor_name", "message", "consent_accepted_at", "first_submitted_at", "info_request_message",
            "decision_reason", "documents", "events", "requirements", "payment", "my_role", "internal_notes", "can_edit",
            "responsible", "visit_starts_at",
        ]

    def _role(self, obj):
        return services.role_for(self.context["request"].user, obj)

    def get_responsible(self, obj) -> dict:
        """Destinataire du dossier, déduit de l'annonce (jamais d'un identifiant fourni par le client) ; sans coordonnées."""
        owner = obj.listing.owner
        profile = getattr(owner, "profile", None)
        return {"name": owner.public_name, "role": owner.role, "role_label": owner.get_role_display(),
                "agency_name": getattr(profile, "agency_name", "") or ""}

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


class FeeDeclareSerializer(serializers.Serializer):
    provider_reference = serializers.RegexField(r"^[A-Za-z0-9_\-]{6,64}$", error_messages={"invalid": "Référence Wave invalide."})


class AdminFeeConfirmSerializer(serializers.Serializer):
    provider_reference = serializers.RegexField(r"^[A-Za-z0-9_\-]{6,64}$", error_messages={"invalid": "Référence Wave invalide."})
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class AdminFeeRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)


class AdminFeePaymentSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    reference = serializers.CharField(read_only=True)
    application_id = serializers.UUIDField(source="application.id", read_only=True)
    application_status = serializers.CharField(source="application.status", read_only=True)
    listing_title = serializers.CharField(source="application.listing.title", read_only=True)
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationFeePayment
        fields = ["id", "amount", "currency", "status", "status_label", "reference", "provider_reference", "checkout_started_at",
                  "declared_at", "confirmed_at", "failure_reason", "application_id", "application_status", "listing_title",
                  "customer_name", "created_at"]

    def get_customer_name(self, obj) -> str:
        return obj.application.customer.full_name
