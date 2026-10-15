from django.utils import timezone

from apps.listings.models import TransactionType

DISCLAIMER = (
    "AVERTISSEMENT — Document généré automatiquement par E-Courtier (version 1). La signature recueillie sur la "
    "plateforme est une signature électronique simple (consentement horodaté associé à l'empreinte du document). "
    "Elle ne constitue pas une signature électronique qualifiée et sa valeur probante peut être contestée. "
    "Pour une vente immobilière, l'acte authentique doit être établi par un notaire. Faites relire ce document "
    "par un professionnel du droit avant tout engagement."
)


def _money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " FCFA"


def render(contract) -> str:
    tx = contract.transaction
    listing = contract.listing
    kind = "CONTRAT DE BAIL D'HABITATION" if listing.transaction_type == TransactionType.RENT else "PROMESSE DE VENTE (PROJET)"
    lines = [
        kind,
        "",
        f"Référence du dossier : {tx.reference}",
        f"Date de génération : {timezone.localtime():%d/%m/%Y %H:%M} (heure de Dakar)",
    ]
    if contract.is_simulated:
        lines += ["", "*** DOCUMENT DE DÉMONSTRATION — PAIEMENT SIMULÉ, AUCUNE VALEUR CONTRACTUELLE ***"]
    lines += [
        "",
        "ENTRE LES SOUSSIGNÉS",
        f"- {contract.owner.full_name}, ci-après « le Bailleur / Vendeur » ;",
        f"- {contract.customer.full_name}, ci-après « le Preneur / Acquéreur ».",
        "",
        "OBJET",
        f"Bien : {listing.get_property_type_display()} — « {listing.title} »",
        f"Situation : {listing.district}, {listing.city}" + (f" — {listing.address_private}" if listing.address_private else ""),
        f"Pièces : {listing.rooms} — Chambres : {listing.bedrooms} — Salles de bain : {listing.bathrooms}"
        + (f" — Surface : {listing.surface_m2} m²" if listing.surface_m2 else ""),
        f"Meublé : {'oui' if listing.is_furnished else 'non'}",
        "",
        "CONDITIONS FINANCIÈRES",
    ]
    if listing.transaction_type == TransactionType.RENT:
        lines.append(f"Loyer mensuel : {_money(listing.price)}")
    else:
        lines.append(f"Prix de vente convenu : {_money(listing.price)}")
    lines += [
        f"{tx.get_amount_kind_display()} réglé via E-Courtier : {_money(tx.amount)}",
        f"Frais de dossier E-Courtier (non remboursables, distincts du montant ci-dessus) : {_money(tx.fee_amount)}",
        f"Statut du paiement : {tx.get_status_display()}" + (" (simulé)" if tx.is_simulated else ""),
        "",
        "E-Courtier n'agit pas comme séquestre : aucun fonds n'est bloqué ni libéré automatiquement par la plateforme.",
    ]
    if contract.special_terms:
        lines += ["", "CLAUSES PARTICULIÈRES", contract.special_terms]
    lines += ["", DISCLAIMER]
    return "\n".join(lines)
