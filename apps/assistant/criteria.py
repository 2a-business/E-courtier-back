"""Critères de recherche de l'assistant : extraction par règles, validation de la sortie LLM et conversion
en paramètres de recherche. Toute valeur issue du LLM est revalidée ici ; rien n'est pris pour argent comptant."""

import difflib
import json
import re
import unicodedata

from apps.listings.models import Amenity, PropertyType, TransactionType
from apps.listings.selectors import public_listings
from apps.listings.text import normalize
from apps.search.serializers import SearchParamsSerializer

FIELDS = (
    "transaction_type", "property_type", "city", "district", "budget_min", "budget_max", "rooms",
    "bedrooms_min", "surface_min", "furnished", "amenities", "verified_only",
)

KNOWN_CITIES = ["Dakar", "Pikine", "Guédiawaye", "Rufisque", "Thiès", "Mbour", "Saly", "Saint-Louis", "Touba",
                "Kaolack", "Ziguinchor", "Diamniadio", "Lac Rose", "Somone"]
KNOWN_DISTRICTS = [
    "Almadies", "Ngor", "Ouakam", "Mermoz", "Sacré-Cœur", "Fann", "Fann Hock", "Point E", "Plateau", "Médina",
    "Gueule Tapée", "Liberté 6", "Sicap", "Sicap Liberté", "Grand Yoff", "HLM", "Parcelles Assainies", "Yoff",
    "Ouest Foire", "Nord Foire", "Mamelles", "Hann Maristes", "Dieuppeul", "Castors", "Patte d'Oie", "Cité Keur Gorgui",
    "Zone B", "Bourguiba", "Keur Massar", "Golf Sud", "Cambérène", "Virage",
]

NUMBER_WORDS = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8}

PROPERTY_WORDS = [
    # appart, apparts, appartement(s), apart, apartement, appt (variantes et fautes courantes).
    (r"\bap+art?(?:e?ments?)?s?\b|\bap+ts?\b", PropertyType.APARTMENT), (r"\bvillas?\b", PropertyType.VILLA),
    (r"\bmaisons?\b", PropertyType.HOUSE), (r"\bstudios?\b", PropertyType.STUDIO),
    (r"\bterrains?\b|\bparcelles? a batir\b", PropertyType.LAND), (r"\bbureaux?\b|\blocal commercial\b", PropertyType.OFFICE),
]


# Vocabulaire corrigé en cas de faute de frappe (« appartemnt », « studo », « locaton »…).
VOCABULARY = (
    "appartement", "appartements", "studio", "studios", "villa", "villas", "maison", "maisons", "chambre",
    "chambres", "location", "louer", "acheter", "achat", "vente", "meuble", "meubles", "terrain", "bureau",
)
BROWSE = r"\b(annonces?|logements?|biens?|offres?|tout|toutes|tous|disponibles?|site|catalogue|liste|propositions?)\b"
GENERIC_WORDS = {"site", "web", "donne", "donnez", "moi", "les", "des", "une", "pour", "avec", "dans", "tout", "toutes",
                 "annonce", "annonces", "logement", "logements", "cherche", "recherche", "voudrais", "veux", "louer",
                 "appart", "apparts", "appartement", "appartements", "maison", "villa", "studio", "chambre", "prix"}


def correct_typos(text: str) -> str:
    """Remplace les mots proches du vocabulaire immobilier (≥ 5 lettres) par leur forme correcte."""
    words = []
    for word in text.split():
        if len(word) >= 5 and word not in VOCABULARY:
            close = difflib.get_close_matches(word, VOCABULARY, n=1, cutoff=0.82)
            word = close[0] if close else word
        words.append(word)
    return " ".join(words)


def strip_accents(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def empty() -> dict:
    return {f: None for f in FIELDS} | {"amenities": []}


def _amount(number: str, unit: str | None) -> int | None:
    number = number.replace(" ", "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        value = float(number)
    except ValueError:
        return None
    unit = (unit or "").strip()
    if unit.startswith("million") or unit in ("m", "millions"):
        value *= 1_000_000
    elif unit in ("k", "mille", "milles"):
        value *= 1_000
    return int(value)


AMOUNT = r"(\d{1,3}(?:[ . ]\d{3})+|\d+(?:,\d+)?)\s*(millions?|mille|k|m)?\b"


def extract_rules(message: str, amenity_index=None, places=None) -> dict:
    text = correct_typos(normalize(message))
    raw = message.lower()
    c = empty()

    rent = bool(re.search(r"\b(louer|location|a louer|loyer|par mois|mensuel)\b", text) or "/mois" in raw)
    sale = bool(re.search(r"\b(acheter|achat|vente|a vendre|acquerir)\b", text))
    if rent and sale:
        c["_ambiguous_transaction"] = True  # « louer ou acheter » : on ne choisit pas à la place du client
    elif rent:
        c["transaction_type"] = TransactionType.RENT
    elif sale:
        c["transaction_type"] = TransactionType.SALE
    c["_browse"] = bool(re.search(BROWSE, text))
    c["_compare"] = bool(re.search(r"\bcompar", text))

    types = [ptype.value for pattern, ptype in PROPERTY_WORDS if re.search(pattern, text)]
    if not types and not re.search(r"\d+\s*pieces?", text) and (
        re.search(r"\b(une|1) chambre\b(?! .*\bpieces?\b)", text)
        or re.search(r"\bchambres? (a louer|meublees?|pour etudiants?)\b", text)
        or re.match(r"chambres?\b", text)
    ):
        types = [PropertyType.ROOM.value]
    c["property_type"] = types or None

    m = re.search(r"\b(\d+|" + "|".join(NUMBER_WORDS) + r")\s*pieces?\b", text) or re.search(r"\b[ft]([1-8])\b", text)
    if m:
        c["rooms"] = int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS[m.group(1)]
    m = re.search(r"\b(\d+|" + "|".join(NUMBER_WORDS) + r")\s*chambres\b", text)
    if m:
        c["bedrooms_min"] = int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS[m.group(1)]
    m = re.search(r"(\d+)\s*(?:m2|m²|metres? carres?)", raw.replace("mètres", "metres").replace("carrés", "carres"))
    if m:
        c["surface_min"] = int(m.group(1))

    lowered = strip_accents(raw).replace("’", "'")
    lowered = re.sub(r"\b(fcfa|cfa|francs?|xof)\b", " ", lowered)
    m = re.search(r"entre\s+" + AMOUNT + r"\s+et\s+" + AMOUNT, lowered)
    if m:
        # « entre 200 et 450 millions » : l'unité finale s'applique aussi à la borne basse.
        c["budget_min"] = _amount(m.group(1), m.group(2) or m.group(4))
        c["budget_max"] = _amount(m.group(3), m.group(4))
    else:
        m = re.search(r"(?:moins de|max(?:imum)?|jusqu'?a|budget(?: de| max)?|pas plus de|inferieur a|<)\s*:?\s*" + AMOUNT, lowered)
        if m:
            c["budget_max"] = _amount(m.group(1), m.group(2))
        m = re.search(r"(?:plus de|au moins|minimum|a partir de)\s+" + AMOUNT, lowered)
        if m and not re.search(r"\bpieces?|chambres?|m2|m²", lowered[m.end():m.end() + 10]):
            c["budget_min"] = _amount(m.group(1), m.group(2))
    for key in ("budget_min", "budget_max"):
        if c[key] is not None and c[key] < 1000:
            c[key] = None  # « moins de 3 » n'est pas un budget

    if re.search(r"\bnon meubles?\b|\bvide\b", text):
        c["furnished"] = False
    elif re.search(r"\bmeubles?\b", text):
        c["furnished"] = True
    if re.search(r"\bverifie(e|es|s)?\b", text):
        c["verified_only"] = True

    cities, districts = places or known_places()
    c["district"] = _longest_match(text, districts)
    c["city"] = _longest_match(text, cities)
    amenity_index = amenity_index if amenity_index is not None else build_amenity_index()
    c["amenities"] = sorted({slug for term, slug in amenity_index if re.search(rf"\b{re.escape(term)}s?\b", text)})
    return c


def _longest_match(text: str, names) -> str | None:
    best = None
    for name in names:
        key = normalize(name)
        if key and re.search(rf"\b{re.escape(key)}\b", text) and (best is None or len(key) > len(normalize(best))):
            best = name
    return best or _fuzzy_match(text, names)


def _fuzzy_match(text: str, names) -> str | None:
    """Lieu mal orthographié (« Kenya » → « Kenia », « Ziginchor » → « Ziguinchor ») : même initiale, forte similarité."""
    keys = {normalize(n): n for n in names if len(normalize(n)) >= 4}
    words = [w for w in text.split() if len(w) >= 4 and w not in GENERIC_WORDS]
    candidates = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
    best, best_score = None, 0.0
    for cand in candidates:
        for key, name in keys.items():
            if key[0] != cand[0]:
                continue
            score = difflib.SequenceMatcher(None, cand, key).ratio()
            if score >= 0.8 and score > best_score:
                best, best_score = name, score
    return best


def canonical_place(value: str | None, names) -> str | None:
    """Ramène un lieu (issu du LLM ou des règles) à son orthographe réelle dans les annonces, si elle est proche."""
    if not value:
        return value
    key = normalize(value)
    for name in names:
        if normalize(name) == key:
            return name
    return _fuzzy_match(key, names) or value


def known_places():
    rows = public_listings().values_list("city", "district").distinct()
    cities = set(KNOWN_CITIES) | {r[0] for r in rows}
    districts = set(KNOWN_DISTRICTS) | {r[1] for r in rows}
    return cities, districts


def build_amenity_index():
    index = []
    for amenity in Amenity.objects.all():
        terms = [amenity.label, amenity.slug.replace("-", " ")] + [s for s in amenity.synonyms.split(",") if s.strip()]
        index += [(normalize(t), amenity.slug) for t in terms if normalize(t)]
    return index


def parse_llm_output(text: str) -> dict:
    """Valide strictement le JSON du LLM. Lève ValueError si inexploitable."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("JSON objet attendu")
    c = empty()
    intent = data.get("intent") if data.get("intent") in ("search", "greeting", "other") else "search"
    if data.get("transaction_type") in TransactionType.values:
        c["transaction_type"] = data["transaction_type"]
    ptypes = data.get("property_type")
    ptypes = [ptypes] if isinstance(ptypes, str) else ptypes or []
    c["property_type"] = [p for p in ptypes if p in PropertyType.values] or None
    for key, low, high in (("budget_min", 1000, 10**11), ("budget_max", 1000, 10**11), ("rooms", 1, 50),
                           ("bedrooms_min", 0, 50), ("surface_min", 5, 100000)):
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high:
            c[key] = int(value)
    for key in ("city", "district"):
        if isinstance(data.get(key), str) and 1 < len(data[key].strip()) <= 80:
            c[key] = data[key].strip()
    if isinstance(data.get("furnished"), bool):
        c["furnished"] = data["furnished"]
    if data.get("verified_only") is True:
        c["verified_only"] = True
    if isinstance(data.get("amenities"), list):
        known = dict(build_amenity_index())
        slugs = set(Amenity.objects.values_list("slug", flat=True))
        found = set()
        for item in data["amenities"][:10]:
            if isinstance(item, str):
                key = normalize(item)
                if item in slugs:
                    found.add(item)
                elif key in known:
                    found.add(known[key])
        c["amenities"] = sorted(found)
    c["_intent"] = intent
    c["_reset"] = data.get("reset") is True
    return c


def merge(previous: dict, new: dict) -> dict:
    """Affinage : les nouveaux critères non vides remplacent les anciens ; reset repart de zéro."""
    if new.get("_reset") or not previous:
        base = empty()
    else:
        base = {f: previous.get(f) for f in FIELDS}
    for f in FIELDS:
        value = new.get(f)
        if value not in (None, [], ""):
            base[f] = value
    return base


def has_criteria(c: dict) -> bool:
    return any(c.get(f) not in (None, [], "") for f in FIELDS)


def to_search_params(c: dict, *, relaxed: bool = False) -> dict:
    raw = {
        "transaction_type": c.get("transaction_type"),
        "property_type": c.get("property_type"),
        "price_min": c.get("budget_min"),
        "price_max": int(c["budget_max"] * 1.15) if relaxed and c.get("budget_max") else c.get("budget_max"),
        "surface_min": c.get("surface_min"),
        "bedrooms_min": c.get("bedrooms_min"),
        "city": c.get("city"),
        "district": None if relaxed and c.get("city") else c.get("district"),
        "furnished": c.get("furnished"),
        "verified": bool(c.get("verified_only")),
        "amenities": None if relaxed else (c.get("amenities") or None),
    }
    if c.get("rooms"):
        raw["rooms_min"] = c["rooms"] if not relaxed else max(1, c["rooms"] - 1)
        if not relaxed:
            raw["rooms_max"] = c["rooms"]
    serializer = SearchParamsSerializer(data={k: v for k, v in raw.items() if v not in (None, [], "")})
    serializer.is_valid(raise_exception=False)
    if serializer.errors:
        # Les critères invalides sont ignorés plutôt que de fausser la recherche.
        clean = {k: v for k, v in serializer.initial_data.items() if k not in serializer.errors}
        serializer = SearchParamsSerializer(data=clean)
        serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def describe(c: dict) -> str:
    parts = []
    labels = dict(PropertyType.choices)
    if c.get("property_type"):
        parts.append(" ou ".join(labels[p].lower() for p in c["property_type"]))
    if c.get("transaction_type"):
        parts.append("à louer" if c["transaction_type"] == "RENT" else "à acheter")
    if c.get("rooms"):
        parts.append(f"{c['rooms']} pièce{'s' if c['rooms'] > 1 else ''}")
    if c.get("bedrooms_min"):
        parts.append(f"{c['bedrooms_min']} chambre(s) minimum")
    if c.get("district"):
        parts.append(f"à {c['district']}")
    elif c.get("city"):
        parts.append(f"à {c['city']}")
    fmt = lambda v: f"{v:,}".replace(",", " ") + " FCFA"  # noqa: E731
    if c.get("budget_min") and c.get("budget_max"):
        parts.append(f"entre {fmt(c['budget_min'])} et {fmt(c['budget_max'])}")
    elif c.get("budget_max"):
        parts.append(f"jusqu'à {fmt(c['budget_max'])}")
    elif c.get("budget_min"):
        parts.append(f"à partir de {fmt(c['budget_min'])}")
    if c.get("surface_min"):
        parts.append(f"{c['surface_min']} m² minimum")
    if c.get("furnished") is True:
        parts.append("meublé")
    elif c.get("furnished") is False:
        parts.append("non meublé")
    if c.get("amenities"):
        names = dict(Amenity.objects.filter(slug__in=c["amenities"]).values_list("slug", "label"))
        parts.append("avec " + ", ".join(names.get(s, s).lower() for s in c["amenities"]))
    if c.get("verified_only"):
        parts.append("annonces vérifiées uniquement")
    return ", ".join(parts)
