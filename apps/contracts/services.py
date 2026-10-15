"""Cycle d'un contrat : DRAFT → PENDING_SIGNATURE → SIGNED, ou CANCELLED.

Toute nouvelle version invalide les signatures précédentes (on signe toujours la dernière empreinte).
"""

import hashlib

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core_errors import BusinessError, Conflict, Forbidden, InvalidTransition
from apps.moderation.services import log_action
from apps.notifications.services import notify

from . import templates
from .models import Contract, ContractSignature, ContractStatus, ContractVersion, SignerRole

CONSENT_TEXT = "J'ai lu le document et j'accepte de le signer électroniquement (signature simple, non qualifiée)."


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _new_version(contract: Contract, actor=None) -> ContractVersion:
    last = contract.versions.order_by("-number").first()
    content = templates.render(contract)
    return ContractVersion.objects.create(
        contract=contract, number=(last.number + 1) if last else 1, content=content,
        content_sha256=_sha(content), created_by=actor,
    )


@transaction.atomic
def create_draft_for_transaction(tx) -> Contract:
    contract, created = Contract.objects.get_or_create(
        transaction=tx,
        defaults={"listing": tx.listing, "customer": tx.customer, "owner": tx.owner, "is_simulated": tx.is_simulated},
    )
    if created:
        _new_version(contract)
    return contract


def _can_edit(actor, contract) -> bool:
    return actor.is_admin or actor.pk == contract.owner_id


@transaction.atomic
def update_terms(*, actor, contract: Contract, special_terms: str) -> Contract:
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    if not _can_edit(actor, contract):
        raise Forbidden("Seul le propriétaire / agent ou un administrateur peut modifier le contrat.")
    if contract.status != ContractStatus.DRAFT:
        raise InvalidTransition("Le contrat ne peut être modifié qu'à l'état de brouillon.")
    contract.special_terms = special_terms
    contract.save(update_fields=["special_terms"])
    _new_version(contract, actor)
    log_action(actor=actor, action="contract.version_created", target=contract)
    return contract


@transaction.atomic
def send_for_signature(*, actor, contract: Contract) -> Contract:
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    if not _can_edit(actor, contract):
        raise Forbidden("Seul le propriétaire / agent ou un administrateur peut envoyer le contrat.")
    if contract.status != ContractStatus.DRAFT:
        raise InvalidTransition("Seul un brouillon peut être envoyé pour signature.")
    contract.status = ContractStatus.PENDING_SIGNATURE
    contract.sent_at = timezone.now()
    contract.save(update_fields=["status", "sent_at"])
    log_action(actor=actor, action="contract.sent", target=contract)
    notify(contract.customer, kind="contract.sent", title="Contrat à signer",
           body=f"Dossier {contract.transaction.reference}.", link=f"/contrats/{contract.pk}", sms=True)
    return contract


@transaction.atomic
def sign(*, actor, contract: Contract, version_number: int, consent: bool, ip: str | None, user_agent: str) -> Contract:
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    if contract.status != ContractStatus.PENDING_SIGNATURE:
        raise InvalidTransition("Ce contrat n'est pas en attente de signature.")
    if actor.pk == contract.customer_id:
        role = SignerRole.CUSTOMER
    elif actor.pk == contract.owner_id:
        role = SignerRole.OWNER
    else:
        raise Forbidden("Vous n'êtes pas partie à ce contrat.")
    if not consent:
        raise BusinessError("Le consentement explicite est obligatoire.", code="consent_required")
    version = contract.current_version
    if version.number != version_number:
        raise Conflict("Le document a changé depuis votre lecture. Relisez la dernière version.", code="stale_version")
    try:
        with transaction.atomic():
            ContractSignature.objects.create(
                contract=contract, version=version, signer=actor, role=role, signed_sha256=version.content_sha256,
                consent_text=CONSENT_TEXT, ip_address=ip, user_agent=user_agent[:200],
            )
    except IntegrityError:
        raise Conflict("Vous avez déjà signé cette version.", code="already_signed")
    log_action(actor=actor, action="contract.signed", target=contract, metadata={"role": role, "version": version.number})
    if version.signatures.count() == 2:
        contract.status = ContractStatus.SIGNED
        contract.signed_at = timezone.now()
        contract.save(update_fields=["status", "signed_at"])
        for user in (contract.customer, contract.owner):
            notify(user, kind="contract.signed", title="Contrat signé par les deux parties",
                   body=f"Dossier {contract.transaction.reference}.", link=f"/contrats/{contract.pk}")
    else:
        other = contract.owner if role == SignerRole.CUSTOMER else contract.customer
        notify(other, kind="contract.partially_signed", title="Le contrat attend votre signature",
               body=f"Dossier {contract.transaction.reference}.", link=f"/contrats/{contract.pk}")
    return contract


@transaction.atomic
def cancel(*, actor, contract: Contract, reason: str) -> Contract:
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    if not _can_edit(actor, contract):
        raise Forbidden("Action non autorisée.")
    if contract.status not in (ContractStatus.DRAFT, ContractStatus.PENDING_SIGNATURE):
        raise InvalidTransition("Un contrat signé ou déjà annulé ne peut pas être annulé ici.")
    if not reason.strip():
        raise BusinessError("Un motif est obligatoire.", code="reason_required")
    contract.status = ContractStatus.CANCELLED
    contract.cancelled_at = timezone.now()
    contract.cancel_reason = reason[:300]
    contract.save(update_fields=["status", "cancelled_at", "cancel_reason"])
    log_action(actor=actor, action="contract.cancelled", target=contract, metadata={"reason": reason[:200]})
    return contract


def cancel_for_transaction(tx, *, actor, reason: str) -> None:
    contract = Contract.objects.filter(transaction=tx).first()
    if contract and contract.status in (ContractStatus.DRAFT, ContractStatus.PENDING_SIGNATURE):
        contract.status = ContractStatus.CANCELLED
        contract.cancelled_at = timezone.now()
        contract.cancel_reason = reason
        contract.save(update_fields=["status", "cancelled_at", "cancel_reason"])
        log_action(actor=actor, action="contract.cancelled", target=contract, metadata={"reason": reason})


def visible_to(user, contract) -> bool:
    return user.is_admin or user.pk in (contract.customer_id, contract.owner_id)
