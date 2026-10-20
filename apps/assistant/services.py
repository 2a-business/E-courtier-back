"""Orchestration de l'assistant.

Flux : message → session et quotas → extraction des critères (LLM si disponible, sinon règles) →
validation → recherche réelle PostgreSQL → réponse déterministe. Un seul appel LLM par demande
(plus au maximum LLM_MAX_RETRIES reprises bornées). Le LLM ne voit jamais la base de données.
"""

import hashlib
import json
import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, transaction

from apps.core_errors import BusinessError
from apps.listings.models import Amenity, PropertyType

from . import criteria as crit
from . import quota
from .models import Conversation, LLMCallLog, Message
from .providers import get_provider
from .providers.base import RETRYABLE, ProviderError, RateLimited

logger = logging.getLogger("ecourtier.assistant")
COOLDOWN_KEY = "assistant:llm_cooldown"
MAX_BACKOFF_SECONDS = 2.0

SYSTEM_PROMPT = """Tu extrais des critères de recherche immobilière au Sénégal à partir d'un message en français.
Réponds UNIQUEMENT par un objet JSON, sans texte autour, avec ces clés (null si non précisé) :
intent: "search" | "greeting" | "other"
reset: true si l'utilisateur commence une nouvelle recherche sans rapport avec les critères précédents, sinon false
transaction_type: "RENT" | "SALE" | null
property_type: liste parmi {ptypes} ou null
city: string | null
district: string | null (quartier, ex. "Fann Hock", "Almadies")
budget_min: entier en FCFA | null
budget_max: entier en FCFA | null
rooms: entier (nombre de pièces) | null
bedrooms_min: entier | null
surface_min: entier en m² | null
furnished: true | false | null
amenities: liste parmi {amenities}
verified_only: true | false
Synonymes : appart, apparts, appartement, F2/F3 → APARTMENT ; maison → HOUSE ; chambre à louer → ROOM.
Une demande générale (« les apparts du site », « vos logements disponibles ») est intent "search".
Corrige les fautes évidentes de lieu (« Ziginchor » → "Ziguinchor").
N'invente jamais de valeur absente du message. Ne propose aucune annonce. "300k" = 300000 ; "1,5 million" = 1500000."""


def anon_key_for(request) -> str:
    raw = f"{request.META.get('REMOTE_ADDR', '')}|{request.META.get('HTTP_USER_AGENT', '')[:120]}|{settings.SECRET_KEY}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_conversation(conversation_id, user, anon_key) -> Conversation | None:
    if not conversation_id:
        return None
    qs = Conversation.objects.filter(pk=conversation_id)
    qs = qs.filter(user=user) if user and user.is_authenticated else qs.filter(user__isnull=True, anon_key=anon_key)
    return qs.first()


def _log_call(provider, status, started, http_status=None, tokens_in=0, tokens_out=0):
    LLMCallLog.objects.create(
        provider=provider.name, model=provider.model, status=status, http_status=http_status,
        latency_ms=int((time.monotonic() - started) * 1000), tokens_in=tokens_in, tokens_out=tokens_out,
    )


def call_llm(provider, *, user_prompt: str, scope: str):
    """Retourne le dict de critères validé, ou None si le LLM est indisponible (le repli prend le relais)."""
    if cache.get(COOLDOWN_KEY):
        return None
    system = SYSTEM_PROMPT.format(
        ptypes=", ".join(PropertyType.values),
        amenities=", ".join(Amenity.objects.values_list("slug", flat=True)) or "(aucune)",
    )
    attempts = 1 + max(0, settings.LLM_MAX_RETRIES)
    for attempt in range(attempts):
        if not quota.reserve_provider_call():
            logger.warning("Plafond global d'appels fournisseur atteint")
            return None
        started = time.monotonic()
        try:
            result = provider.complete_json(system=system, user=user_prompt, max_tokens=settings.LLM_MAX_OUTPUT_TOKENS)
        except RETRYABLE as exc:
            _log_call(provider, exc.status, started, exc.http_status)
            if isinstance(exc, RateLimited):
                cache.set(COOLDOWN_KEY, True, max(settings.LLM_COOLDOWN_SECONDS, int(exc.retry_after or 0)))
                if not exc.retry_after or exc.retry_after > MAX_BACKOFF_SECONDS:
                    return None
            if attempt + 1 < attempts:
                time.sleep(min(MAX_BACKOFF_SECONDS, exc.retry_after or 0.5 * (2 ** attempt)))
                continue
            return None
        except ProviderError as exc:
            _log_call(provider, exc.status, started, exc.http_status)
            return None
        quota.record_tokens(scope, result.tokens_in, result.tokens_out)
        try:
            parsed = crit.parse_llm_output(result.text)
        except (ValueError, json.JSONDecodeError):
            _log_call(provider, "invalid", started, result.http_status, result.tokens_in, result.tokens_out)
            return None
        _log_call(provider, "ok", started, result.http_status, result.tokens_in, result.tokens_out)
        return parsed
    return None


GREETING_WORDS = ("bonjour", "salut", "bonsoir", "hello", "salam", "nanga def", "merci")
HELP_TEXT = (
    "Je peux chercher pour vous parmi les annonces publiées sur E-Courtier. Décrivez le logement : type, "
    "location ou achat, quartier ou ville, budget en FCFA, nombre de pièces, équipements. "
    "Exemple : « Appartement 3 pièces à louer à Fann Hock, moins de 300 000 FCFA, avec balcon »."
)


class SearchUnavailable(BusinessError):
    """La base n'a pas pu être interrogée : jamais présenté comme une absence d'annonces."""

    code = "search_unavailable"
    http_status = 503

    def __init__(self):
        super().__init__("La recherche d'annonces est momentanément indisponible. Réessayez dans un instant : "
                         "cela ne signifie pas qu'aucune annonce ne correspond.")


def _fmt_price(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " FCFA"


def _listing_line(listing) -> str:
    """Faits réels d'une annonce (aucune donnée inventée)."""
    suffix = " / mois" if listing.transaction_type == "RENT" else ""
    parts = [f"« {listing.title} »", listing.get_property_type_display(), f"{_fmt_price(listing.price)}{suffix}",
             f"{listing.district}, {listing.city}", f"{listing.rooms} pièce{'s' if listing.rooms > 1 else ''}"]
    if listing.surface_m2:
        parts.append(f"{listing.surface_m2} m²")
    if listing.is_verified:
        parts.append("vérifiée")
    return " — ".join(parts)


WITH_ARTICLE = {
    "APARTMENT": "un appartement", "HOUSE": "une maison", "VILLA": "une villa", "STUDIO": "un studio",
    "ROOM": "une chambre", "LAND": "un terrain", "OFFICE": "un bureau ou local",
}


def _mismatch_note(found, criteria) -> str:
    """Signale honnêtement une annonce retenue par son titre alors que l'annonceur l'a classée autrement."""
    if not found.type_mismatches or not criteria.get("property_type"):
        return ""
    wanted = " ou ".join(WITH_ARTICLE[t] for t in criteria["property_type"])
    notes = [f"« {listing.title} » est classée « {listing.get_property_type_display()} » par l'annonceur"
             for listing in found.type_mismatches]
    return f" Remarque : {' ; '.join(notes)}, mais son titre évoque {wanted} ; vérifiez le détail de l'annonce."


def _compare(conversation) -> tuple[str, list]:
    from apps.listings.selectors import card_queryset

    last = conversation.messages.filter(role="assistant").exclude(listing_ids=[]).order_by("-created_at").first()
    ids = (last.listing_ids if last else [])[:4]
    listings = {str(listing.pk): listing for listing in card_queryset().filter(pk__in=ids)}
    ordered = [listings[i] for i in ids if i in listings]
    if len(ordered) < 2:
        return ("Pour comparer, lancez d'abord une recherche qui renvoie au moins deux annonces, puis demandez « compare-les ».", ordered)
    lines = [f"{n}. {_listing_line(listing)}" for n, listing in enumerate(ordered, 1)]
    cheapest = min(ordered, key=lambda listing: listing.price)
    return ("Comparaison des annonces affichées (données des annonces publiées) :\n" + "\n".join(lines)
            + f"\nLa moins chère : « {cheapest.title} ».", ordered)


def handle_message(*, user, anon_key: str, text: str, conversation_id=None) -> dict:
    from . import finder

    text = text.strip()[: settings.ASSISTANT_MAX_MESSAGE_CHARS]
    scope, limit = quota.user_scope(user, anon_key)
    configured = get_provider()
    llm_allowed, remaining = quota.consume_request(scope, limit, wants_llm=configured is not None)

    conversation = get_conversation(conversation_id, user, anon_key)
    if conversation is None:
        conversation = Conversation.objects.create(
            user=user if user and user.is_authenticated else None,
            anon_key="" if user and user.is_authenticated else anon_key,
        )
    previous = conversation.last_criteria or {}

    try:
        places = crit.known_places()
        rules = crit.extract_rules(text, places=places)  # signaux déterministes, utilisés dans tous les modes
    except DatabaseError:
        logger.exception("Assistant : lecture des lieux impossible")
        raise SearchUnavailable()

    provider = configured if llm_allowed else None
    parsed, mode = None, "rules"
    if provider:
        recent = list(conversation.messages.filter(role="user").order_by("-created_at")[: settings.ASSISTANT_HISTORY_MESSAGES])
        history = "\n".join(f"- {m.text[:200]}" for m in reversed(recent))
        prompt = (
            f"Critères précédents : {json.dumps({k: v for k, v in previous.items() if v not in (None, [])}, ensure_ascii=False)}\n"
            + (f"Messages précédents :\n{history}\n" if history else "")
            + f"Nouveau message : {text}"
        )
        parsed = call_llm(provider, user_prompt=prompt, scope=scope)
        mode = "llm" if parsed is not None else "fallback"
        if parsed is not None:
            # Le LLM interprète ; les règles complètent ce qu'il a laissé vide (jamais l'inverse).
            for key in crit.FIELDS:
                if parsed.get(key) in (None, [], "") and rules.get(key) not in (None, [], ""):
                    parsed[key] = rules[key]
    if parsed is None:
        parsed = dict(rules)
        parsed["_intent"] = "search" if crit.has_criteria(parsed) or rules["_browse"] else (
            "greeting" if any(w in crit.normalize(text) for w in GREETING_WORDS) else "other"
        )
        # Sans LLM, un message avec de nouveaux critères de type/transaction relance une recherche.
        parsed["_reset"] = bool(parsed.get("transaction_type") or parsed.get("property_type")) and bool(previous)
    for key in ("city", "district"):
        parsed[key] = crit.canonical_place(parsed.get(key), places[0] if key == "city" else places[1])

    with transaction.atomic():
        Message.objects.create(conversation=conversation, role="user", text=text)
        if rules["_compare"]:
            reply, compared = _compare(conversation)
            Message.objects.create(conversation=conversation, role="assistant", text=reply, mode=mode,
                                   listing_ids=[str(listing.pk) for listing in compared])
            return _payload(conversation, reply, previous, compared, [], mode, remaining)

        if not crit.has_criteria(parsed):
            if rules["_browse"]:
                # « Donne-moi les annonces du site » : catalogue complet des annonces publiées.
                parsed["_reset"] = True
            elif parsed.get("_intent") != "search":
                reply = ("Bonjour ! " if parsed.get("_intent") == "greeting" else "") + HELP_TEXT
                Message.objects.create(conversation=conversation, role="assistant", text=reply, mode=mode)
                return _payload(conversation, reply, previous, [], [], mode, remaining)

        merged = crit.merge(previous, parsed)
        try:
            found = finder.find(merged, limit=settings.ASSISTANT_RESULTS_LIMIT)
        except DatabaseError:
            logger.exception("Assistant : recherche d'annonces impossible")
            raise SearchUnavailable()

        summary = crit.describe(merged)
        target = f" à : {summary}" if summary else " à votre recherche"
        if found.results:
            shown = len(found.results)
            plural = "s" if found.total > 1 else ""
            reply = (f"J'ai trouvé {found.total} annonce{plural} publiée{plural}" + (f" pour : {summary}." if summary else ".")
                     + (f" Voici les {shown} plus pertinentes." if found.total > shown else ""))
        elif found.alternatives:
            reply = (f"Aucune annonce publiée ne correspond exactement{target}. "
                     f"En élargissant ({', '.join(found.relaxed)}), voici {len(found.alternatives)} annonce"
                     f"{'s' if len(found.alternatives) > 1 else ''} proche{'s' if len(found.alternatives) > 1 else ''}.")
        else:
            reply = f"Aucune annonce publiée ne correspond{target}, même en élargissant les critères."
            if found.lowest_price:
                reply += f" Pour ce type de recherche, la moins chère actuellement publiée est à {_fmt_price(found.lowest_price)}."
            reply += " Vous pouvez modifier le budget, la ville ou le type de bien."
        reply += _mismatch_note(found, merged)
        if rules.get("_ambiguous_transaction") and not merged.get("transaction_type"):
            reply += " Souhaitez-vous louer ou acheter ? Précisez-le pour affiner."
        if mode == "fallback":
            reply += " (Assistant IA momentanément indisponible : analyse simplifiée de votre demande.)"

        conversation.last_criteria = merged
        conversation.save(update_fields=["last_criteria", "updated_at"])
        Message.objects.create(
            conversation=conversation, role="assistant", text=reply, criteria=merged, mode=mode,
            listing_ids=[str(listing.pk) for listing in found.results + found.alternatives],
        )
    return _payload(conversation, reply, merged, found.results, found.alternatives, mode, remaining,
                    total=found.total, relaxed=found.relaxed)


def _payload(conversation, reply, criteria, results, alternatives, mode, remaining, *, total=None, relaxed=None):
    return {
        "total": len(results) if total is None else total,
        "relaxed": relaxed or [],
        "conversation_id": str(conversation.pk),
        "reply": reply,
        "criteria": criteria,
        "results": results,
        "alternatives": alternatives,
        "mode": mode,
        "remaining_today": remaining,
    }
