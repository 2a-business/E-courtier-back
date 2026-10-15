"""Quotas journaliers persistés en base (fiables même avec plusieurs processus)."""

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core_errors import BusinessError

from .models import DailyUsage

GLOBAL = "global"


class QuotaExceeded(BusinessError):
    code = "assistant_quota_exceeded"
    http_status = 429


def _row(scope: str) -> DailyUsage:
    row, _ = DailyUsage.objects.get_or_create(date=timezone.localdate(), scope=scope)
    return DailyUsage.objects.select_for_update().get(pk=row.pk)


def user_scope(user, anon_key: str) -> tuple[str, int]:
    if user and user.is_authenticated:
        return f"user:{user.pk}", settings.ASSISTANT_USER_DAILY_REQUESTS
    return f"anon:{anon_key[:40]}", settings.ASSISTANT_ANON_DAILY_REQUESTS


@transaction.atomic
def consume_request(scope: str, limit: int, wants_llm: bool = True) -> tuple[bool, int]:
    """Compte une demande. Retourne (llm_autorisé, demandes restantes pour l'utilisateur).

    Le dépassement de la limite individuelle bloque la demande ; le dépassement de la limite globale
    n'autorise plus que le mode déterministe (sans coût)."""
    personal = _row(scope)
    if personal.requests >= limit:
        raise QuotaExceeded(
            "Vous avez atteint la limite quotidienne de l'assistant. Utilisez la recherche avancée ou revenez demain."
        )
    glob = _row(GLOBAL)
    personal.requests = F("requests") + 1
    personal.save(update_fields=["requests"])
    glob.requests = F("requests") + 1
    # Seules les demandes réellement envoyées à un fournisseur consomment le quota LLM.
    llm_allowed = wants_llm and glob.llm_requests < settings.ASSISTANT_GLOBAL_DAILY_REQUESTS
    if llm_allowed:
        glob.llm_requests = F("llm_requests") + 1
    glob.save(update_fields=["requests", "llm_requests"] if llm_allowed else ["requests"])
    personal.refresh_from_db()
    return llm_allowed, max(0, limit - personal.requests)


@transaction.atomic
def reserve_provider_call() -> bool:
    glob = _row(GLOBAL)
    if glob.provider_calls >= settings.ASSISTANT_GLOBAL_DAILY_PROVIDER_CALLS:
        return False
    glob.provider_calls = F("provider_calls") + 1
    glob.save(update_fields=["provider_calls"])
    return True


def record_tokens(scope: str, tokens_in: int, tokens_out: int) -> None:
    today = timezone.localdate()
    for s in (GLOBAL, scope):
        DailyUsage.objects.filter(date=today, scope=s).update(
            tokens_in=F("tokens_in") + tokens_in, tokens_out=F("tokens_out") + tokens_out
        )


def today_usage() -> dict:
    row = DailyUsage.objects.filter(date=timezone.localdate(), scope=GLOBAL).first()
    return {
        "requests": row.requests if row else 0,
        "llm_requests": row.llm_requests if row else 0,
        "provider_calls": row.provider_calls if row else 0,
        "tokens_in": row.tokens_in if row else 0,
        "tokens_out": row.tokens_out if row else 0,
        "llm_requests_limit": settings.ASSISTANT_GLOBAL_DAILY_REQUESTS,
        "provider_calls_limit": settings.ASSISTANT_GLOBAL_DAILY_PROVIDER_CALLS,
    }
