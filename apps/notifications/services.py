from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string

from .models import Notification, SmsStatus


def get_sms_backend():
    return import_string(settings.SMS_BACKEND)()


def notify(user, *, kind: str, title: str, body: str, link: str = "", sms: bool = False) -> Notification:
    """Crée une notification dans l'application et, si demandé, tente un SMS via l'adaptateur configuré."""
    sms_status = SmsStatus.NOT_REQUESTED
    if sms:
        sms_status = get_sms_backend().send(user.phone, f"E-Courtier : {title}") if user.phone else SmsStatus.NO_PHONE
    return Notification.objects.create(
        user=user, kind=kind, title=title[:140], body=body[:1000], link=link, sms_status=sms_status
    )


def mark_read(user, notification_ids=None) -> int:
    qs = Notification.objects.filter(user=user, read_at__isnull=True)
    if notification_ids:
        qs = qs.filter(pk__in=notification_ids)
    return qs.update(read_at=timezone.now())
