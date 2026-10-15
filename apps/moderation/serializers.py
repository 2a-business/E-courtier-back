from rest_framework import serializers

from .models import AuditLog, Report, ReportReason, ReportStatus


class ReportCreateSerializer(serializers.Serializer):
    listing = serializers.UUIDField()
    reason = serializers.ChoiceField(choices=ReportReason.choices)
    details = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class ReportSerializer(serializers.ModelSerializer):
    reason_label = serializers.CharField(source="get_reason_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    listing_title = serializers.CharField(source="listing.title", read_only=True)

    class Meta:
        model = Report
        fields = ["id", "listing", "listing_title", "reason", "reason_label", "details", "status", "status_label",
                  "resolution_note", "created_at", "handled_at"]


class AdminReportSerializer(ReportSerializer):
    reporter_email = serializers.CharField(source="reporter.email", read_only=True)
    listing_status = serializers.CharField(source="listing.publication_status", read_only=True)

    class Meta(ReportSerializer.Meta):
        fields = ReportSerializer.Meta.fields + ["reporter_email", "listing_status"]


class ReportHandleSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[ReportStatus.IN_REVIEW, ReportStatus.RESOLVED, ReportStatus.DISMISSED])
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    suspend_listing = serializers.BooleanField(default=False)


class AuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ["id", "actor_email", "action", "target_type", "target_id", "metadata", "created_at"]

    def get_actor_email(self, obj) -> str:
        return obj.actor.email if obj.actor else "système"
