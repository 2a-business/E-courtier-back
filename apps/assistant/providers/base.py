from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    http_status: int = 200


class ProviderError(Exception):
    """Erreur générique du fournisseur (réponse invalide, 4xx hors 429)."""

    status = "error"

    def __init__(self, message: str, http_status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.http_status = http_status
        self.retry_after = retry_after


class RateLimited(ProviderError):
    status = "rate_limited"


class ServerError(ProviderError):
    status = "server_error"


class Timeout(ProviderError):
    status = "timeout"


RETRYABLE = (RateLimited, ServerError, Timeout)


class LLMProvider(Protocol):
    name: str
    model: str

    def complete_json(self, *, system: str, user: str, max_tokens: int) -> LLMResult:
        """Un seul appel HTTP. Lève une sous-classe de ProviderError en cas d'échec."""
