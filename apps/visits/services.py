"""Réservation de visites.

La disponibilité est revérifiée sous verrou (SELECT … FOR UPDATE sur le créneau) et une contrainte
d'unicité conditionnelle en base empêche deux visites actives sur un même créneau, même en cas de
requêtes concurrentes.
"""

from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core_errors import BusinessError, Conflict, Forbidden, InvalidTransition
from apps.listings.models import PublicationStatus
from apps.listings.services import ensure_can_manage
from apps.notifications.services import notify

from .models import ACTIVE_VISIT_STATUSES, Visit, VisitSlot, VisitStatus

MIN_NOTICE = timedelta(hours=1)
MAX_SLOTS_PER_BATCH = 60


def _fmt(dt) -> str:
    return timezone.localtime(dt).strftime("%d/%m/%Y à %H:%M")


@transaction.atomic
def create_slots(*, actor, listing, date, start_time, end_time, duration_minutes: int) -> list[VisitSlot]:
    ensure_can_manage(actor, listing)
    if duration_minutes < 15 or duration_minutes > 240:
        raise BusinessError("Durée d'un créneau : entre 15 et 240 minutes.")
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(date, start_time), tz)
    end = timezone.make_aware(datetime.combine(date, end_time), tz)
    if end <= start:
        raise BusinessError("L'heure de fin doit suivre l'heure de début.")
    if start < timezone.now() + MIN_NOTICE:
        raise BusinessError("Les créneaux doivent commencer au moins une heure après maintenant.")
    step = timedelta(minutes=duration_minutes)
    existing = set(VisitSlot.objects.filter(listing=listing, starts_at__gte=start, starts_at__lt=end).values_list("starts_at", flat=True))
    slots, cursor = [], start
    while cursor + step <= end:
        if cursor not in existing:
            slots.append(VisitSlot(listing=listing, host=listing.owner, starts_at=cursor, ends_at=cursor + step))
        cursor += step
    if len(slots) > MAX_SLOTS_PER_BATCH:
        raise BusinessError(f"Maximum {MAX_SLOTS_PER_BATCH} créneaux par opération.")
    return VisitSlot.objects.bulk_create(slots)


@transaction.atomic
def remove_slot(*, actor, slot: VisitSlot) -> None:
    ensure_can_manage(actor, slot.listing)
    slot = VisitSlot.objects.select_for_update().get(pk=slot.pk)
    if slot.visits.filter(status__in=ACTIVE_VISIT_STATUSES).exists():
        raise Conflict("Ce créneau a une visite active : annulez-la d'abord.")
    if slot.visits.exists():
        slot.is_active = False
        slot.save(update_fields=["is_active"])
    else:
        slot.delete()


def book_visit(*, customer, slot_id: int, message: str = "") -> Visit:
    try:
        with transaction.atomic():
            slot = VisitSlot.objects.select_for_update().select_related("listing").get(pk=slot_id)
            listing = slot.listing
            if listing.publication_status != PublicationStatus.PUBLISHED:
                raise BusinessError("Cette annonce n'est plus disponible.", code="listing_unavailable")
            if listing.owner_id == customer.pk:
                raise Forbidden("Vous ne pouvez pas réserver une visite de votre propre annonce.")
            if not slot.is_active or slot.starts_at < timezone.now() + MIN_NOTICE:
                raise Conflict("Ce créneau n'est plus disponible.", code="slot_unavailable")
            if Visit.objects.filter(slot=slot, status__in=ACTIVE_VISIT_STATUSES).exists():
                raise Conflict("Ce créneau vient d'être réservé. Choisissez-en un autre.", code="slot_taken")
            if Visit.objects.filter(listing=listing, customer=customer, status__in=ACTIVE_VISIT_STATUSES).exists():
                raise Conflict("Vous avez déjà une visite en cours pour ce logement.", code="already_booked")
            visit = Visit.objects.create(
                listing=listing, slot=slot, customer=customer, host=listing.owner, message=message[:500]
            )
    except IntegrityError:
        # Course perdue face à une autre transaction : la contrainte unique a protégé le créneau.
        raise Conflict("Ce créneau vient d'être réservé. Choisissez-en un autre.", code="slot_taken")

    notify(
        visit.host, kind="visit.requested", title="Nouvelle demande de visite",
        body=f"{customer.public_name} souhaite visiter « {listing.title} » le {_fmt(slot.starts_at)}.",
        link="/tableau-de-bord?onglet=visites", sms=True,
    )
    notify(
        customer, kind="visit.requested", title="Demande de visite envoyée",
        body=f"« {listing.title} » le {_fmt(slot.starts_at)}. En attente de confirmation.",
        link=f"/visites/{visit.pk}",
    )
    return visit


TRANSITIONS = {
    VisitStatus.PENDING: {VisitStatus.CONFIRMED, VisitStatus.CANCELLED},
    VisitStatus.CONFIRMED: {VisitStatus.COMPLETED, VisitStatus.CANCELLED},
    VisitStatus.CANCELLED: set(),
    VisitStatus.COMPLETED: set(),
}


@transaction.atomic
def change_status(*, actor, visit: Visit, target: str, reason: str = "") -> Visit:
    visit = Visit.objects.select_for_update().select_related("slot", "listing", "customer", "host").get(pk=visit.pk)
    is_host = actor.pk == visit.host_id or actor.is_admin
    is_customer = actor.pk == visit.customer_id
    if not (is_host or is_customer):
        raise Forbidden("Cette visite ne vous concerne pas.")
    if target not in TRANSITIONS[VisitStatus(visit.status)]:
        raise InvalidTransition(f"Impossible de passer de « {visit.get_status_display()} » à {target}.")

    now = timezone.now()
    if target == VisitStatus.CONFIRMED:
        if not is_host:
            raise Forbidden("Seul le propriétaire ou l'agent peut confirmer.")
        if visit.slot.starts_at <= now:
            raise BusinessError("Le créneau est passé.")
        visit.confirmed_at = now
    elif target == VisitStatus.COMPLETED:
        if not is_host:
            raise Forbidden("Seul le propriétaire ou l'agent peut marquer la visite comme effectuée.")
        if visit.slot.starts_at > now:
            raise BusinessError("La visite n'a pas encore eu lieu.")
        visit.completed_at = now
    elif target == VisitStatus.CANCELLED:
        visit.cancelled_at = now
        visit.cancelled_by = actor
        visit.cancel_reason = reason[:300]
    visit.status = target
    visit.save()

    other = visit.customer if is_host else visit.host
    labels = {
        VisitStatus.CONFIRMED: "Visite confirmée",
        VisitStatus.CANCELLED: "Visite annulée",
        VisitStatus.COMPLETED: "Visite effectuée",
    }
    notify(
        other, kind=f"visit.{target.lower()}", title=labels[target],
        body=f"« {visit.listing.title} » — {_fmt(visit.slot.starts_at)}" + (f". Motif : {reason[:200]}" if reason else ""),
        link=f"/visites/{visit.pk}", sms=target != VisitStatus.COMPLETED,
    )
    return visit


def send_due_reminders(now=None) -> int:
    """Rappel unique pour les visites confirmées des prochaines 24 h (commande planifiable)."""
    now = now or timezone.now()
    due = Visit.objects.filter(
        status=VisitStatus.CONFIRMED, reminder_sent_at__isnull=True,
        slot__starts_at__gt=now, slot__starts_at__lte=now + timedelta(hours=24),
    ).select_related("slot", "listing", "customer", "host")
    count = 0
    for visit in due:
        with transaction.atomic():
            updated = Visit.objects.filter(pk=visit.pk, reminder_sent_at__isnull=True).update(reminder_sent_at=now)
            if not updated:
                continue
            for user in (visit.customer, visit.host):
                notify(
                    user, kind="visit.reminder", title="Rappel de visite",
                    body=f"« {visit.listing.title} » le {_fmt(visit.slot.starts_at)}.", link=f"/visites/{visit.pk}", sms=True,
                )
            count += 1
    return count
