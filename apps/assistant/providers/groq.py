import httpx

from .base import LLMResult, ProviderError
from .http import post_json

BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider:
    name = "groq"

    def __init__(self, *, api_key: str, model: str, timeout: float, client: httpx.Client | None = None):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.client = client or httpx.Client()

    def complete_json(self, *, system: str, user: str, max_tokens: int) -> LLMResult:
        data = post_json(
            self.client,
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            payload={
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Réponse Groq inattendue")
        usage = data.get("usage", {})
        return LLMResult(text=text, tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0))
