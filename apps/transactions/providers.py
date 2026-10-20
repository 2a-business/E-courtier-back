"""Adaptateurs de paiement.

Un lien Wave Business est un lien marchand statique : le client y saisit le montant (ou paie le montant figé dans
le lien, paramètre ``amount``) puis confirme dans son application Wave. E-Courtier ne reçoit aucune notification
automatique dans ce mode ; un administrateur rapproche le paiement depuis le tableau de bord Wave Business avant de
le confirmer. Ce mode ne permet ni séquestre, ni blocage, ni libération automatique des fonds.
"""

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from django.conf import settings

from apps.core_errors import BusinessError


@dataclass
class Checkout:
    url: str
    instructions: str
    auto_confirmation: bool


def fixed_amount(link: str) -> int | None:
    """Montant figé dans le lien Wave (``?amount=7500``), ou None si le client saisit le montant."""
    values = parse_qs(urlparse(link).query).get("amount")
    if not values:
        return None
    try:
        return int(float(values[0]))
    except ValueError:
        return -1  # montant illisible : traité comme incohérent


def link_problem(link: str, amount: int) -> str | None:
    """Raison pour laquelle ce lien ne peut pas servir à payer ``amount`` FCFA, ou None s'il est utilisable."""
    if not link:
        return "Le paiement Wave n'est pas configuré sur cet environnement."
    parsed = urlparse(link)
    if parsed.scheme != "https" or not parsed.hostname:
        return "Le lien de paiement Wave configuré est invalide."
    fixed = fixed_amount(link)
    if fixed is not None and fixed != amount:
        shown = f"{fixed:,}".replace(",", " ") if fixed >= 0 else "illisible"
        due = f"{amount:,}".replace(",", " ")
        return (f"Le lien Wave configuré est fixé à {shown} FCFA alors que le montant dû est de {due} FCFA : "
                "paiement désactivé jusqu'à la correction du lien par E-Courtier.")
    return None


def checkout(link: str, *, amount: int, reference: str) -> Checkout:
    """Lien vérifié pour ``amount`` FCFA, ou BusinessError 503 explicite (lien absent, invalide ou montant incohérent)."""
    problem = link_problem(link, amount)
    if problem:
        code = "payment_not_configured" if not link else "payment_link_invalid"
        raise BusinessError(problem, code=code, http_status=503)
    total = f"{amount:,}".replace(",", " ")
    entry = "Le montant est déjà renseigné dans Wave." if fixed_amount(link) is not None else f"Dans Wave, saisissez exactement {total} FCFA."
    return Checkout(
        url=link,
        instructions=(
            f"{entry} Indiquez si possible la référence {reference}. Revenez ensuite sur E-Courtier pour indiquer "
            "l'identifiant de transaction Wave. Le paiement sera confirmé après vérification par notre équipe."
        ),
        auto_confirmation=False,
    )


def dossier_fee_link() -> str:
    """Lien dédié aux frais de dossier s'il existe, sinon le lien marchand général."""
    return (getattr(settings, "WAVE_DOSSIER_FEE_LINK", "") or settings.WAVE_PAYMENT_LINK or "").strip()


class WaveLinkProvider:
    code = "WAVE_LINK"

    def start(self, transaction) -> Checkout:
        return checkout((settings.WAVE_PAYMENT_LINK or "").strip(), amount=transaction.total_amount, reference=transaction.reference)


def get_provider():
    return WaveLinkProvider()
