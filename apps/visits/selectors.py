from django.db.models import Exists, OuterRef
from django.utils import timezone

from .models import ACTIVE_VISIT_STATUSES, Visit, VisitSlot, VisitStatus


def available_slots(listing, *, start=None, end=None):
    taken = Visit.objects.filter(slot=OuterRef("pk"), status__in=ACTIVE_VISIT_STATUSES)
    qs = VisitSlot.objects.filter(listing=listing, is_active=True, starts_at__gt=start or timezone.now())
    if end:
        qs = qs.filter(starts_at__lt=end)
    return qs.annotate(taken=Exists(taken)).filter(taken=False).order_by("starts_at")


def user_can_see_exact_address(user, listing) -> bool:
    if not (user and user.is_authenticated):
        return False
    if user.is_admin or listing.owner_id == user.pk:
        return True
    return Visit.objects.filter(
        listing=listing, customer=user, status__in=[VisitStatus.CONFIRMED, VisitStatus.COMPLETED]
    ).exists()


def visits_for(user, role: str):
    qs = Visit.objects.select_related("listing", "slot", "customer", "host").prefetch_related("listing__photos")
    if role == "host":
        return qs.filter(host=user)
    return qs.filter(customer=user)
