"""Dossiers de transaction et paiements.

Règles :
- une transaction PENDING n'est jamais considérée comme payée ;
- le retour du navigateur depuis Wave ne change aucun statut ;
- seul un administrateur (après rapprochement Wave) ou le mode simulation (hors production) passe en PAID ;
- les frais de dossier sont stockés et affichés séparément du montant du logement.
"""

import secrets

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core_errors import BusinessError, Conflict, Forbidden, InvalidTransition
from apps.listings.models import Listing, PublicationStatus, TransactionType
from apps.moderation.services import log_action
from apps.notifications.services import notify
from apps.visits.models import Visit, VisitStatus

from .models import (
    AmountKind,
    AttemptStatus,
    PaymentAttempt,
    Provider,
    Transaction,
    TransactionEvent,
    TransactionStatus,
)
from .providers import get_provider

TRANSITIONS = {
    TransactionStatus.PENDING: {TransactionStatus.PAID, TransactionStatus.FAILED, TransactionStatus.CANCELLED},
    TransactionStatus.PAID: {TransactionStatus.REFUNDED},
    TransactionStatus.FAILED: set(),
    TransactionStatus.CANCELLED: set(),
    TransactionStatus.REFUNDED: set(),
}


def _reference_used_by_fee(reference: str) -> bool:
    """Une référence Wave déjà utilisée pour des frais de dossier ne peut pas justifier un autre paiement."""
    from apps.applications.models import ApplicationFeePayment

    return ApplicationFeePayment.objects.filter(provider_reference=reference).exists()


def _reference() -> str:
    return f"EC-{timezone.now():%y%m%d}-{secrets.token_hex(3).upper()}"


def compute_amounts(listing: Listing) -> tuple[int, str, int]:
    if listing.transaction_type == TransactionType.RENT:
        # Location : les frais de dossier sont réglés une seule fois, via le dossier locatif (apps.applications).
        return listing.price, AmountKind.FIRST_MONTH_RENT, 0
    deposit = listing.price * settings.SALE_DEPOSIT_PERCENT // 100
    return deposit, AmountKind.RESERVATION_DEPOSIT, settings.DOSSIER_FEE_XOF


def quote(listing: Listing) -> dict:
    amount, kind, fee = compute_amounts(listing)
    return {
        "amount": amount, "amount_kind": kind, "amount_kind_label": AmountKind(kind).label,
        "fee_amount": fee, "total_amount": amount + fee, "currency": "XOF",
        "sale_deposit_percent": settings.SALE_DEPOSIT_PERCENT if kind == AmountKind.RESERVATION_DEPOSIT else None,
    }


def _event(tx, event, actor=None, from_status="", to_status="", note=""):
    TransactionEvent.objects.create(
        transaction=tx, event=event, actor=actor, from_status=from_status, to_status=to_status, note=note[:300]
    )


def create_transaction(*, customer, listing_id, idempotency_key: str = "") -> tuple[Transaction, bool]:
    """Retourne (transaction, created). Une clé d'idempotence rejouée renvoie la transaction existante."""
    if idempotency_key:
        existing = Transaction.objects.filter(customer=customer, idempotency_key=idempotency_key).first()
        if existing:
            return existing, False
    try:
        with transaction.atomic():
            listing = Listing.objects.select_for_update().get(pk=listing_id)
            if listing.publication_status != PublicationStatus.PUBLISHED:
                raise BusinessError("Cette annonce n'est plus disponible.", code="listing_unavailable")
            if listing.owner_id == customer.pk:
                raise Forbidden("Vous ne pouvez pas ouvrir un dossier sur votre propre annonce.")
            visited = Visit.objects.filter(
                listing=listing, customer=customer, status__in=[VisitStatus.CONFIRMED, VisitStatus.COMPLETED]
            ).exists()
            if not visited:
                raise BusinessError(
                    "Un dossier ne peut être ouvert qu'après une visite confirmée.", code="visit_required"
                )
            if Transaction.objects.filter(listing=listing, status=TransactionStatus.PAID).exists():
                raise Conflict("Ce logement fait déjà l'objet d'un dossier payé.", code="listing_taken")
            pending = Transaction.objects.filter(customer=customer, listing=listing, status=TransactionStatus.PENDING).first()
            if pending:
                return pending, False
            amount, kind, fee = compute_amounts(listing)
            tx = Transaction.objects.create(
                reference=_reference(), customer=customer, listing=listing, owner=listing.owner,
                amount=amount, amount_kind=kind, fee_amount=fee, idempotency_key=idempotency_key[:64],
            )
            _event(tx, "created", actor=customer, to_status=TransactionStatus.PENDING)
    except IntegrityError:
        # Double clic ou requêtes concurrentes : on renvoie le dossier déjà créé.
        tx = Transaction.objects.filter(customer=customer, listing_id=listing_id, status=TransactionStatus.PENDING).first()
        if tx is None:
            raise Conflict("Un dossier est déjà en cours de création.")
        return tx, False
    log_action(actor=customer, action="transaction.created", target=tx, metadata={"reference": tx.reference})
    return tx, True


@transaction.atomic
def start_wave_payment(*, customer, tx: Transaction) -> tuple[PaymentAttempt, dict]:
    tx = Transaction.objects.select_for_update().get(pk=tx.pk)
    if tx.customer_id != customer.pk:
        raise Forbidden("Ce dossier ne vous appartient pas.")
    if tx.status != TransactionStatus.PENDING:
        raise InvalidTransition("Ce dossier n'est plus en attente de paiement.")
    # Lève payment_not_configured (503) avant toute écriture si aucun lien marchand n'est configuré.
    checkout = get_provider().start(tx)
    # Idempotent : un nouveau clic (ou « Rouvrir Wave ») réutilise la tentative ouverte au lieu d'en empiler.
    attempt = _open_wave_attempt(tx)
    if attempt is None:
        attempt = PaymentAttempt.objects.create(transaction=tx, provider=Provider.WAVE_LINK, checkout_url=checkout.url)
        _event(tx, "payment_started", actor=customer, note="Redirection vers Wave Business")
    elif attempt.checkout_url != checkout.url:
        attempt.checkout_url = checkout.url
        attempt.save(update_fields=["checkout_url"])
    return attempt, {"url": checkout.url, "instructions": checkout.instructions, "auto_confirmation": checkout.auto_confirmation}


def _open_wave_attempt(tx: Transaction) -> PaymentAttempt | None:
    """Dernière tentative Wave démarrée et non clôturée (redirigée ou déclarée par le client)."""
    return (
        tx.attempts.filter(provider=Provider.WAVE_LINK, status__in=[AttemptStatus.INITIATED, AttemptStatus.CUSTOMER_DECLARED])
        .order_by("-created_at")
        .first()
    )


@transaction.atomic
def declare_payment(*, customer, tx: Transaction, provider_reference: str) -> PaymentAttempt:
    """Le client indique avoir payé. Le statut reste PENDING jusqu'à vérification."""
    tx = Transaction.objects.select_for_update().get(pk=tx.pk)
    if tx.customer_id != customer.pk:
        raise Forbidden("Ce dossier ne vous appartient pas.")
    if tx.status != TransactionStatus.PENDING:
        raise InvalidTransition("Ce dossier n'est plus en attente de paiement.")
    reference = provider_reference.strip().upper()
    if _reference_used_by_fee(reference) or PaymentAttempt.objects.filter(provider=Provider.WAVE_LINK, provider_reference=reference).exclude(transaction=tx).exists():
        raise Conflict("Cette référence Wave est déjà associée à un autre dossier.", code="duplicate_reference")
    # Une déclaration n'est possible qu'après une redirection réelle vers Wave (lien marchand configuré).
    # Une seconde déclaration corrige la référence de la même tentative ; le statut reste PENDING.
    attempt = _open_wave_attempt(tx)
    if attempt is None:
        raise BusinessError(
            "Démarrez d'abord le paiement avec Wave : aucune redirection vers Wave n'a été enregistrée pour ce dossier.",
            code="payment_not_started", http_status=409,
        )
    attempt.provider_reference = reference
    attempt.status = AttemptStatus.CUSTOMER_DECLARED
    attempt.declared_at = timezone.now()
    try:
        with transaction.atomic():
            attempt.save()
    except IntegrityError:
        raise Conflict("Cette référence Wave est déjà utilisée.", code="duplicate_reference")
    _event(tx, "payment_declared", actor=customer, note=f"Référence déclarée : {reference}")
    return attempt


def _mark_paid(tx: Transaction, *, actor, simulated: bool, note: str):
    old = tx.status
    if TransactionStatus.PAID not in TRANSITIONS[TransactionStatus(old)]:
        raise InvalidTransition("Ce dossier ne peut plus être marqué comme payé.")
    if Transaction.objects.filter(listing_id=tx.listing_id, status=TransactionStatus.PAID).exclude(pk=tx.pk).exists():
        raise Conflict("Un autre dossier payé existe déjà pour ce logement.", code="listing_taken")
    tx.status = TransactionStatus.PAID
    tx.paid_at = timezone.now()
    tx.is_simulated = simulated
    if simulated:
        tx.provider = Provider.SIMULATION
    tx.save()
    _event(tx, "paid_simulated" if simulated else "paid_confirmed", actor=actor, from_status=old, to_status=tx.status, note=note)

    from apps.contracts.services import create_draft_for_transaction

    create_draft_for_transaction(tx)
    suffix = " (SIMULATION — aucun argent n'a circulé)" if simulated else ""
    for user in (tx.customer, tx.owner):
        notify(
            user, kind="transaction.paid", title=f"Paiement confirmé{suffix}",
            body=f"Dossier {tx.reference} — « {tx.listing.title} ». Le contrat est en préparation.",
            link=f"/paiement/{tx.pk}", sms=not simulated,
        )


@transaction.atomic
def confirm_payment(*, actor, tx: Transaction, provider_reference: str, note: str = "") -> Transaction:
    """Confirmation manuelle par un administrateur après rapprochement dans Wave Business."""
    if not actor.is_admin:
        raise Forbidden("Seul un administrateur peut confirmer un paiement.")
    tx = Transaction.objects.select_for_update().select_related("listing", "customer", "owner").get(pk=tx.pk)
    reference = provider_reference.strip().upper()
    if not reference:
        raise BusinessError("La référence Wave vérifiée est obligatoire.", code="reference_required")
    if _reference_used_by_fee(reference) or PaymentAttempt.objects.filter(provider=Provider.WAVE_LINK, provider_reference=reference).exclude(transaction=tx).exists():
        raise Conflict("Cette référence Wave est déjà associée à un autre dossier.", code="duplicate_reference")
    attempt = tx.attempts.filter(provider=Provider.WAVE_LINK, provider_reference=reference).first() or \
        tx.attempts.filter(provider=Provider.WAVE_LINK).exclude(status=AttemptStatus.REJECTED).first() or \
        PaymentAttempt(transaction=tx, provider=Provider.WAVE_LINK)
    attempt.provider_reference = reference
    attempt.status = AttemptStatus.CONFIRMED
    attempt.confirmed_at = timezone.now()
    attempt.confirmed_by = actor
    _mark_paid(tx, actor=actor, simulated=False, note=note or f"Rapproché avec la transaction Wave {reference}")
    attempt.save()
    log_action(actor=actor, action="transaction.paid_confirmed", target=tx, metadata={"reference": tx.reference})
    return tx


@transaction.atomic
def simulate_payment(*, actor, tx: Transaction) -> Transaction:
    if not settings.PAYMENT_SIMULATION_ENABLED:
        raise Forbidden("La simulation de paiement est désactivée sur cet environnement.", code="simulation_disabled")
    tx = Transaction.objects.select_for_update().select_related("listing", "customer", "owner").get(pk=tx.pk)
    if tx.customer_id != actor.pk and not actor.is_admin:
        raise Forbidden("Ce dossier ne vous appartient pas.")
    PaymentAttempt.objects.create(
        transaction=tx, provider=Provider.SIMULATION, status=AttemptStatus.CONFIRMED, is_simulated=True,
        confirmed_at=timezone.now(), confirmed_by=actor,
    )
    _mark_paid(tx, actor=actor, simulated=True, note="Paiement simulé (démonstration)")
    log_action(actor=actor, action="transaction.paid_simulated", target=tx, metadata={"reference": tx.reference})
    return tx


@transaction.atomic
def change_status(*, actor, tx: Transaction, target: str, note: str = "") -> Transaction:
    """Annulation (client ou admin), échec ou remboursement (admin)."""
    tx = Transaction.objects.select_for_update().select_related("listing", "customer", "owner").get(pk=tx.pk)
    if target == TransactionStatus.PAID:
        raise BusinessError("Utilisez la confirmation de paiement.")
    if target not in TRANSITIONS[TransactionStatus(tx.status)]:
        raise InvalidTransition(f"Passage de {tx.status} à {target} impossible.")
    if target == TransactionStatus.CANCELLED:
        if not (actor.is_admin or actor.pk == tx.customer_id):
            raise Forbidden("Vous ne pouvez pas annuler ce dossier.")
    elif not actor.is_admin:
        raise Forbidden("Action réservée aux administrateurs.")
    if target in (TransactionStatus.FAILED, TransactionStatus.REFUNDED) and not note.strip():
        raise BusinessError("Un motif est obligatoire.", code="reason_required")
    old = tx.status
    tx.status = target
    tx.save(update_fields=["status", "updated_at"])
    tx.attempts.filter(status__in=[AttemptStatus.INITIATED, AttemptStatus.CUSTOMER_DECLARED]).update(
        status=AttemptStatus.REJECTED
    )
    _event(tx, target.lower(), actor=actor, from_status=old, to_status=target, note=note)
    log_action(actor=actor, action=f"transaction.{target.lower()}", target=tx, metadata={"note": note[:200]})
    if target == TransactionStatus.REFUNDED:
        from apps.contracts.services import cancel_for_transaction

        cancel_for_transaction(tx, actor=actor, reason="Dossier remboursé")
    other = tx.customer if actor.pk != tx.customer_id else tx.owner
    notify(other, kind=f"transaction.{target.lower()}", title=f"Dossier {tx.reference} : {TransactionStatus(target).label}",
           body=note[:300] or tx.listing.title, link=f"/paiement/{tx.pk}")
    return tx


def visible_to(user, tx: Transaction) -> bool:
    return user.is_admin or user.pk in (tx.customer_id, tx.owner_id)
