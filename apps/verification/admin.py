from django.contrib import admin

from .models import VerificationDocument, VerificationRequest


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    list_display = ["listing", "status", "submitted_at", "decided_by", "decided_at"]
    list_filter = ["status"]
    # Les décisions passent par l'API (services.decide) pour garantir la traçabilité.
    readonly_fields = ["listing", "submitted_by", "status", "decided_by", "decided_at", "decision_reason"]


@admin.register(VerificationDocument)
class VerificationDocumentAdmin(admin.ModelAdmin):
    list_display = ["listing", "doc_type", "uploaded_at"]
    exclude = ["file"]
    readonly_fields = ["listing", "request", "doc_type", "original_name", "content_type", "size", "sha256", "uploaded_by"]
