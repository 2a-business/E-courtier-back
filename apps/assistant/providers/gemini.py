import httpx

from .base import LLMResult, ProviderError
from .http import post_json

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"

    def __init__(self, *, api_key: str, model: str, timeout: float, disable_thinking: bool = True, client: httpx.Client | None = None):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.disable_thinking = disable_thinking
        self.client = client or httpx.Client()

    def complete_json(self, *, system: str, user: str, max_tokens: int) -> LLMResult:
        generation = {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"}
        if self.disable_thinking:
            # Les modèles « Flash » 2.5 réfléchissent par défaut, ce qui consomme des jetons de sortie.
            generation["thinkingConfig"] = {"thinkingBudget": 0}
        data = post_json(
            self.client,
            f"{BASE_URL}/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            payload={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": generation,
            },
            timeout=self.timeout,
        )
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Réponse Gemini inattendue")
        usage = data.get("usageMetadata", {})
        return LLMResult(text=text, tokens_in=usage.get("promptTokenCount", 0), tokens_out=usage.get("candidatesTokenCount", 0))
