"""Recherche d'annonces pour l'assistant : la base de données est la seule source de vérité.

S'appuie sur ``apps.search.selectors.search_listings`` (annonces publiées uniquement, mêmes règles que la
recherche du site) et ajoute :
- une tolérance sur le type : une annonce dont le TITRE désigne le type demandé (« Appartement … ») est
  retenue même si l'annonceur l'a classée autrement ; elle est signalée comme telle, jamais reclassée ;
- le nombre total de résultats (la limite d'affichage ne fait jamais conclure à une absence) ;
- un classement par pertinence ;
- des élargissements successifs et expliqués lorsque rien ne correspond exactement.
"""

from dataclasses import dataclass, field

from django.db.models import Case, IntegerField, Min, Q, Value, When

from apps.listings.models import PropertyType
from apps.listings.selectors import public_listings
from apps.search.selectors import search_listings

from . import criteria as crit

# Mots du TITRE qui désignent sans ambiguïté un type de bien (le titre seul : une description qui cite
# « 3 chambres » ne fait pas d'une villa une chambre à louer).
TITLE_TERMS = {
    PropertyType.APARTMENT: ("appart", "apartement", "appt"),
    PropertyType.STUDIO: ("studio",),
    PropertyType.VILLA: ("villa",),
    PropertyType.HOUSE: ("maison",),
    PropertyType.LAND: ("terrain", "parcelle"),
    PropertyType.OFFICE: ("bureau", "local commercial"),
}


@dataclass
class FindResult:
    results: list
    total: int
    alternatives: list = field(default_factory=list)
    relaxed: list = field(default_factory=list)  # libellés des critères élargis pour les alternatives
    type_mismatches: list = field(default_factory=list)  # annonces retenues par leur titre, classées autrement
    lowest_price: int | None = None  # prix minimal réel du type demandé, si rien n'a été trouvé


def _title_q(types) -> Q:
    q = Q()
    for ptype in types or []:
        for term in TITLE_TERMS.get(ptype, ()):
            q |= Q(title__icontains=term)
        if ptype == PropertyType.ROOM:
            q |= Q(title__istartswith="chambre")
    return q


def _title_matches(listing, types) -> bool:
    """Même règle que ``_title_q``, appliquée à une annonce déjà chargée."""
    title = listing.title.lower()
    for ptype in types or []:
        if any(term in title for term in TITLE_TERMS.get(ptype, ())) or (ptype == PropertyType.ROOM and title.startswith("chambre")):
            return True
    return False


def _mismatches(listings, requested) -> list:
    """Annonces retenues uniquement grâce à leur titre (type déclaré différent du type demandé)."""
    return [lst for lst in listings if requested and lst.property_type not in requested and _title_matches(lst, requested)]


def _query(c: dict, *, rooms_wide: bool = False):
    """Annonces publiées correspondant exactement aux critères ``c``, classées par pertinence."""
    params = crit.to_search_params(c)
    if rooms_wide and c.get("rooms"):
        params["rooms_min"], params["rooms_max"] = max(1, c["rooms"] - 1), c["rooms"] + 1
    types = params.pop("property_type", None)
    qs = search_listings(params)
    if types:
        qs = qs.filter(Q(property_type__in=types) | _title_q(types))
        exact_type = Case(When(property_type__in=types, then=Value(1)), default=Value(0), output_field=IntegerField())
    else:
        exact_type = Value(1, output_field=IntegerField())
    district = c.get("district")
    district_hit = (
        Case(When(district_normalized=crit.normalize(district), then=Value(1)), default=Value(0), output_field=IntegerField())
        if district else Value(0, output_field=IntegerField())
    )
    # Pertinence : type exact d'abord, puis quartier demandé, puis annonces les plus récentes.
    return qs.annotate(exact_type=exact_type, district_hit=district_hit).order_by("-exact_type", "-district_hit", "-published_at")


def _relaxations(c: dict) -> list[tuple[dict, list[str]]]:
    """Élargissements successifs, du plus léger au plus large, chacun décrit exactement."""
    light, labels = dict(c), []
    if c.get("budget_max"):
        light["budget_max"] = int(c["budget_max"] * 1.2)
        labels.append("budget augmenté de 20 %")
    if c.get("amenities"):
        light["amenities"] = []
        labels.append("équipements non exigés")
    if c.get("furnished") is not None:
        light["furnished"] = None
        labels.append("meublé ou non")
    if c.get("district") and c.get("city"):
        light["district"] = None
        labels.append(f"toute la ville de {c['city']}")
    if c.get("rooms"):
        labels.append("nombre de pièces ±1")
    steps = [(light, labels)] if labels else []
    current, current_labels = light, labels
    if c.get("property_type"):
        current, current_labels = dict(current, property_type=None), current_labels + ["tous types de biens"]
        steps.append((current, current_labels))
    if c.get("budget_max"):
        current = dict(current, budget_max=int(c["budget_max"] * 1.5))
        current_labels = [lab for lab in current_labels if "20 %" not in lab] + ["budget augmenté de 50 %"]
        steps.append((current, current_labels))
    if c.get("city") or c.get("district"):
        current, current_labels = dict(current, city=None, district=None), [lab for lab in current_labels if "toute la ville" not in lab] + ["toutes les villes"]
        steps.append((current, current_labels))
    return steps


def find(c: dict, *, limit: int) -> FindResult:
    qs = _query(c)
    total = qs.count()
    results = list(qs[:limit])
    requested = set(c.get("property_type") or [])
    if results:
        return FindResult(results=results, total=total, type_mismatches=_mismatches(results, requested))

    for relaxed_c, labels in _relaxations(c):
        alternatives = list(_query(relaxed_c, rooms_wide=True)[:limit])
        if alternatives:
            # Une fois le type élargi, les autres types sont attendus : seuls les titres trompeurs sont signalés.
            return FindResult(results=[], total=0, alternatives=alternatives, relaxed=labels,
                              type_mismatches=_mismatches(alternatives, requested))

    lowest = None
    if c.get("budget_max"):
        base = public_listings()
        if c.get("transaction_type"):
            base = base.filter(transaction_type=c["transaction_type"])
        if requested:
            base = base.filter(Q(property_type__in=requested) | _title_q(requested))
        lowest = base.aggregate(m=Min("price"))["m"]
    return FindResult(results=[], total=0, lowest_price=lowest)
