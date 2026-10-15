"""Sélection du fournisseur LLM selon LLM_PROVIDER. Aucun repli automatique vers un fournisseur payant."""

from django.conf import settings

from .gemini import GeminiProvider
from .groq import GroqProvider


def get_provider():
    name = (settings.LLM_PROVIDER or "rules").lower()
    if name == "rules" or not settings.LLM_API_KEY or not settings.LLM_MODEL:
        return None
    if name == "gemini":
        return GeminiProvider(
            api_key=settings.LLM_API_KEY, model=settings.LLM_MODEL, timeout=settings.LLM_TIMEOUT_SECONDS,
            disable_thinking=getattr(settings, "LLM_GEMINI_DISABLE_THINKING", True),
        )
    if name == "groq":
        return GroqProvider(api_key=settings.LLM_API_KEY, model=settings.LLM_MODEL, timeout=settings.LLM_TIMEOUT_SECONDS)
    return None
