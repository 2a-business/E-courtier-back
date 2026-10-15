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
from django.db import transaction

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


def handle_message(*, user, anon_key: str, text: str, conversation_id=None) -> dict:
    from apps.search.selectors import search_listings

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
    if parsed is None:
        parsed = crit.extract_rules(text)
        parsed["_intent"] = "search" if crit.has_criteria(parsed) else (
            "greeting" if any(w in crit.normalize(text) for w in GREETING_WORDS) else "other"
        )
        # Sans LLM, un message avec de nouveaux critères de type/transaction relance une recherche.
        parsed["_reset"] = bool(parsed.get("transaction_type") or parsed.get("property_type")) and bool(previous)

    with transaction.atomic():
        Message.objects.create(conversation=conversation, role="user", text=text)
        if parsed.get("_intent") != "search" and not crit.has_criteria(parsed):
            reply = ("Bonjour ! " if parsed.get("_intent") == "greeting" else "") + HELP_TEXT
            Message.objects.create(conversation=conversation, role="assistant", text=reply, mode=mode)
            return _payload(conversation, reply, previous, [], [], mode, remaining)

        merged = crit.merge(previous, parsed)
        params = crit.to_search_params(merged)
        results = list(search_listings(params)[: settings.ASSISTANT_RESULTS_LIMIT])
        alternatives = []
        if not results:
            relaxed = crit.to_search_params(merged, relaxed=True)
            alternatives = list(search_listings(relaxed)[: settings.ASSISTANT_RESULTS_LIMIT])

        summary = crit.describe(merged) or "vos critères"
        if results:
            reply = f"Voici {len(results)} logement{'s' if len(results) > 1 else ''} publié{'s' if len(results) > 1 else ''} correspondant à : {summary}."
        elif alternatives:
            reply = (f"Aucune annonce ne correspond exactement à : {summary}. "
                     "Voici des logements proches (budget un peu plus large, quartier ou équipements élargis).")
        else:
            reply = f"Aucune annonce publiée ne correspond pour l'instant à : {summary}. Essayez d'élargir le budget ou le quartier."
        if mode == "fallback":
            reply += " (Assistant IA momentanément indisponible : analyse simplifiée de votre demande.)"

        conversation.last_criteria = merged
        conversation.save(update_fields=["last_criteria", "updated_at"])
        Message.objects.create(
            conversation=conversation, role="assistant", text=reply, criteria=merged, mode=mode,
            listing_ids=[str(listing.pk) for listing in results + alternatives],
        )
    return _payload(conversation, reply, merged, results, alternatives, mode, remaining)


def _payload(conversation, reply, criteria, results, alternatives, mode, remaining):
    return {
        "conversation_id": str(conversation.pk),
        "reply": reply,
        "criteria": criteria,
        "results": results,
        "alternatives": alternatives,
        "mode": mode,
        "remaining_today": remaining,
    }
