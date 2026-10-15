"""Journal d'audit et traitement des signalements."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core_errors import BusinessError, Conflict, Forbidden, InvalidTransition

from .models import REPORT_TRANSITIONS, AuditLog, Report, ReportStatus

_SENSITIVE_KEYS = {"password", "token", "secret", "api_key", "file", "document", "phone", "email"}


def _scrub(metadata: dict) -> dict:
    safe = (str, int, float, bool, type(None))
    return {
        k: v if isinstance(v, safe) else str(v)
        for k, v in (metadata or {}).items()
        if k.lower() not in _SENSITIVE_KEYS
    }


def log_action(*, actor, action: str, target, metadata: dict | None = None) -> AuditLog:
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        target_type=target._meta.label_lower,
        target_id=str(target.pk),
        metadata=_scrub(metadata or {}),
    )


def create_report(*, listing, reporter, reason: str, details: str = "") -> Report:
    if listing.owner_id == reporter.pk:
        raise BusinessError("Vous ne pouvez pas signaler votre propre annonce.")
    try:
        with transaction.atomic():
            report = Report.objects.create(listing=listing, reporter=reporter, reason=reason, details=details)
    except IntegrityError:
        raise Conflict("Vous avez déjà un signalement en cours pour cette annonce.")
    return report


@transaction.atomic
def handle_report(*, actor, report: Report, new_status: str, note: str = "", suspend_listing: bool = False) -> Report:
    if not actor.is_admin:
        raise Forbidden("Action réservée aux administrateurs.")
    report = Report.objects.select_for_update().get(pk=report.pk)
    if new_status not in REPORT_TRANSITIONS[ReportStatus(report.status)]:
        raise InvalidTransition(f"Transition {report.status} → {new_status} interdite.")
    report.status = new_status
    report.resolution_note = note
    report.handled_by = actor
    report.handled_at = timezone.now()
    report.save()
    log_action(actor=actor, action=f"report.{new_status.lower()}", target=report, metadata={"listing": report.listing_id})
    if suspend_listing and new_status == ReportStatus.RESOLVED:
        from apps.listings.services import moderate_listing

        report.listing = moderate_listing(actor=actor, listing=report.listing, action="suspend", reason=f"Signalement #{report.pk}")
    return report
