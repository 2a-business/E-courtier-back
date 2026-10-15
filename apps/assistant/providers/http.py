import httpx

from .base import ProviderError, RateLimited, ServerError, Timeout


def post_json(client: httpx.Client, url: str, *, headers: dict, payload: dict, timeout: float) -> dict:
    try:
        response = client.post(url, headers=headers, json=payload, timeout=timeout)
    except httpx.TimeoutException:
        raise Timeout("Délai dépassé")
    except httpx.HTTPError as exc:
        raise ServerError(f"Erreur réseau : {type(exc).__name__}")
    if response.status_code == 429:
        retry_after = response.headers.get("retry-after")
        try:
            retry_after = float(retry_after) if retry_after else None
        except ValueError:
            retry_after = None
        raise RateLimited("Quota du fournisseur atteint", http_status=429, retry_after=retry_after)
    if response.status_code >= 500:
        raise ServerError("Erreur du fournisseur", http_status=response.status_code)
    if response.status_code >= 400:
        # Ne jamais propager le corps : il peut refléter la requête.
        raise ProviderError("Requête refusée par le fournisseur", http_status=response.status_code)
    try:
        return response.json()
    except ValueError:
        raise ProviderError("Réponse non JSON", http_status=response.status_code)
