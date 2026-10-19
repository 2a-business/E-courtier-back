"""Sélection du fournisseur LLM selon LLM_PROVIDER. Aucun repli automatique vers un fournisseur payant."""

import httpx
from django.conf import settings

from .gemini import GeminiProvider
from .groq import GroqProvider

SUPPORTED_PROVIDERS = ("rules", "gemini", "groq")
_client: httpx.Client | None = None


def _shared_client() -> httpx.Client:
    """Un client HTTP par processus : connexions TLS réutilisées au lieu d'un client (jamais fermé) par requête."""
    global _client
    if _client is None:
        _client = httpx.Client()
    return _client


def get_provider():
    name = (settings.LLM_PROVIDER or "rules").lower()
    if name == "rules" or not settings.LLM_API_KEY or not settings.LLM_MODEL:
        return None
    if name == "gemini":
        return GeminiProvider(
            api_key=settings.LLM_API_KEY, model=settings.LLM_MODEL, timeout=settings.LLM_TIMEOUT_SECONDS,
            disable_thinking=getattr(settings, "LLM_GEMINI_DISABLE_THINKING", True), client=_shared_client(),
        )
    if name == "groq":
        return GroqProvider(
            api_key=settings.LLM_API_KEY, model=settings.LLM_MODEL, timeout=settings.LLM_TIMEOUT_SECONDS, client=_shared_client()
        )
    return None
