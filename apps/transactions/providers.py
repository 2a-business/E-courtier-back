"""Adaptateurs de paiement.

Un lien Wave Business est un lien marchand statique : le client y saisit le montant puis confirme dans
son application Wave. E-Courtier ne reçoit aucune notification automatique dans ce mode ; un
administrateur rapproche le paiement depuis le tableau de bord Wave Business avant de le confirmer.
Ce mode ne permet ni séquestre, ni blocage, ni libération automatique des fonds.
"""

from dataclasses import dataclass

from django.conf import settings

from apps.core_errors import BusinessError


@dataclass
class Checkout:
    url: str
    instructions: str
    auto_confirmation: bool


class WaveLinkProvider:
    code = "WAVE_LINK"

    def start(self, transaction) -> Checkout:
        if not settings.WAVE_PAYMENT_LINK:
            raise BusinessError(
                "Le paiement Wave n'est pas configuré sur cet environnement.", code="payment_not_configured", http_status=503
            )
        total = f"{transaction.total_amount:,}".replace(",", " ")
        return Checkout(
            url=settings.WAVE_PAYMENT_LINK,
            instructions=(
                f"Dans Wave, saisissez exactement {total} FCFA et, si possible, la référence {transaction.reference}. "
                "Revenez ensuite sur E-Courtier pour indiquer l'identifiant de transaction Wave. "
                "Le paiement sera confirmé après vérification par notre équipe."
            ),
            auto_confirmation=False,
        )


def get_provider():
    return WaveLinkProvider()
