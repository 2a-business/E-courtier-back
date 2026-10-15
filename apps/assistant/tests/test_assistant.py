import json

import httpx
import pytest
from django.test import override_settings

from apps.assistant import criteria as crit
from apps.assistant import services
from apps.assistant.models import DailyUsage, LLMCallLog, Message
from apps.assistant.providers.base import LLMResult, RateLimited, ServerError, Timeout
from apps.assistant.providers.gemini import GeminiProvider
from apps.assistant.providers.groq import GroqProvider
from conftest import client_for, make_listing

pytestmark = pytest.mark.django_db
URL = "/api/v1/assistant/chat/"
EXAMPLE = "Je cherche un appartement de trois pièces à Fann Hock à moins de 300 000 FCFA, avec balcon."


class FakeProvider:
    name, model = "fake", "fake-1"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def complete_json(self, *, system, user, max_tokens):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(text=item, tokens_in=50, tokens_out=20)


@pytest.fixture
def catalog(owner):
    return [
        make_listing(owner, title="F3 Fann Hock balcon", price=280000, rooms=3, district="Fann Hock", amenities=["balcon"]),
        make_listing(owner, title="F3 Fann Hock sans balcon", price=250000, rooms=3, district="Fann Hock"),
        make_listing(owner, title="Villa Almadies", price=400000000, rooms=7, property_type="VILLA", transaction_type="SALE", district="Almadies"),
    ]


def use(monkeypatch, provider):
    monkeypatch.setattr(services, "get_provider", lambda: provider)
    monkeypatch.setattr(services.time, "sleep", lambda s: None)


@pytest.mark.parametrize("text,expected", [
    (EXAMPLE, {"property_type": ["APARTMENT"], "rooms": 3, "budget_max": 300000, "district": "Fann Hock", "amenities": ["balcon"]}),
    ("Studio meublé à louer à Mermoz jusqu'à 150k", {"property_type": ["STUDIO"], "transaction_type": "RENT", "furnished": True, "budget_max": 150000, "district": "Mermoz"}),
    ("Villa à vendre aux Almadies entre 200 et 450 millions avec piscine", {"transaction_type": "SALE", "budget_min": 200_000_000, "budget_max": 450_000_000, "amenities": ["piscine"]}),
    ("F4 non meublé avec clim et parking", {"rooms": 4, "furnished": False, "amenities": ["climatisation", "parking"]}),
    ("maison 3 chambres à Thiès budget 1,5 million", {"property_type": ["HOUSE"], "bedrooms_min": 3, "city": "Thiès", "budget_max": 1_500_000}),
])
def test_rules_extraction(catalog, text, expected):
    result = crit.extract_rules(text)
    for key, value in expected.items():
        assert result[key] == value, key


def test_llm_output_is_validated_not_trusted(catalog):
    raw = json.dumps({
        "intent": "search", "transaction_type": "LOUER", "property_type": ["APARTMENT", "CHATEAU"], "budget_max": -5,
        "rooms": 900, "amenities": ["balcon", "héliport"], "district": "Fann Hock", "furnished": "oui",
        "listings": [{"id": "inventé", "price": 1}],
    })
    c = crit.parse_llm_output(raw)
    assert c["transaction_type"] is None and c["property_type"] == ["APARTMENT"]
    assert c["budget_max"] is None and c["rooms"] is None and c["furnished"] is None
    assert c["amenities"] == ["balcon"] and "listings" not in c
    with pytest.raises(ValueError):
        crit.parse_llm_output("[1, 2]")


def test_rules_mode_returns_only_real_listings(api, catalog):
    res = api.post(URL, {"message": EXAMPLE}, format="json")
    assert res.status_code == 200 and res.data["mode"] == "rules"
    assert [r["title"] for r in res.data["results"]] == ["F3 Fann Hock balcon"]
    assert {r["id"] for r in res.data["results"]} <= {str(l.pk) for l in catalog}


def test_llm_mode_single_call_and_refinement(api, catalog, monkeypatch):
    provider = FakeProvider(
        json.dumps({"intent": "search", "property_type": ["APARTMENT"], "district": "Fann Hock", "rooms": 3, "budget_max": 300000}),
        json.dumps({"intent": "search", "reset": False, "amenities": ["balcon"]}),
    )
    use(monkeypatch, provider)
    first = api.post(URL, {"message": "appart 3 pièces Fann Hock 300k"}, format="json").data
    assert first["mode"] == "llm" and len(first["results"]) == 2 and provider.calls == 1
    second = api.post(URL, {"message": "avec balcon", "conversation_id": first["conversation_id"]}, format="json").data
    assert [r["title"] for r in second["results"]] == ["F3 Fann Hock balcon"]
    assert second["criteria"]["district"] == "Fann Hock" and provider.calls == 2
    assert LLMCallLog.objects.filter(status="ok").count() == 2
    usage = DailyUsage.objects.get(scope="global")
    assert usage.tokens_in == 100 and usage.provider_calls == 2


def test_rate_limit_falls_back_and_sets_cooldown(api, catalog, monkeypatch):
    provider = FakeProvider(RateLimited("429", http_status=429, retry_after=30))
    use(monkeypatch, provider)
    res = api.post(URL, {"message": EXAMPLE}, format="json").data
    assert res["mode"] == "fallback" and "indisponible" in res["reply"] and len(res["results"]) == 1
    assert provider.calls == 1  # pas de nouvelle tentative quand Retry-After est long
    # Pendant la temporisation, aucun appel n'est fait.
    api.post(URL, {"message": EXAMPLE}, format="json")
    assert provider.calls == 1


def test_server_error_retried_once_then_success(api, catalog, monkeypatch):
    provider = FakeProvider(ServerError("500", http_status=500), json.dumps({"intent": "search", "district": "Almadies"}))
    use(monkeypatch, provider)
    res = api.post(URL, {"message": "quelque chose aux Almadies"}, format="json").data
    assert res["mode"] == "llm" and provider.calls == 2
    assert [r["title"] for r in res["results"]] == ["Villa Almadies"]


@override_settings(LLM_MAX_RETRIES=1)
def test_retries_are_bounded(api, catalog, monkeypatch):
    provider = FakeProvider(Timeout("t"), Timeout("t"), Timeout("t"))
    use(monkeypatch, provider)
    assert api.post(URL, {"message": EXAMPLE}, format="json").data["mode"] == "fallback"
    assert provider.calls == 2


def test_invalid_json_falls_back(api, catalog, monkeypatch):
    use(monkeypatch, FakeProvider("Voici des annonces : villa à 1 FCFA"))
    assert api.post(URL, {"message": EXAMPLE}, format="json").data["mode"] == "fallback"


@override_settings(ASSISTANT_ANON_DAILY_REQUESTS=2)
def test_per_user_quota(api, catalog):
    for _ in range(2):
        assert api.post(URL, {"message": EXAMPLE}, format="json").status_code == 200
    res = api.post(URL, {"message": EXAMPLE}, format="json")
    assert res.status_code == 429 and res.data["code"] == "assistant_quota_exceeded"


@override_settings(ASSISTANT_GLOBAL_DAILY_REQUESTS=1)
def test_global_llm_quota_switches_to_rules(api, catalog, monkeypatch, customer):
    provider = FakeProvider(json.dumps({"intent": "search", "district": "Fann Hock"}))
    use(monkeypatch, provider)
    assert api.post(URL, {"message": EXAMPLE}, format="json").data["mode"] == "llm"
    res = client_for(customer).post(URL, {"message": EXAMPLE}, format="json").data
    assert res["mode"] == "rules" and provider.calls == 1 and res["results"]


@override_settings(ASSISTANT_GLOBAL_DAILY_PROVIDER_CALLS=0)
def test_provider_call_cap(api, catalog, monkeypatch):
    provider = FakeProvider()
    use(monkeypatch, provider)
    assert api.post(URL, {"message": EXAMPLE}, format="json").data["mode"] == "fallback" and provider.calls == 0


def test_greeting_and_no_results_with_alternatives(api, catalog):
    res = api.post(URL, {"message": "Bonjour"}, format="json").data
    assert res["results"] == [] and "Exemple" in res["reply"]
    res = api.post(URL, {"message": "appartement 3 pièces Fann Hock moins de 260 000 FCFA avec balcon"}, format="json").data
    assert res["results"] == [] and "F3 Fann Hock balcon" in [r["title"] for r in res["alternatives"]]
    assert "Villa Almadies" not in [r["title"] for r in res["alternatives"]]


def test_conversations_are_private(api, catalog, customer):
    conv = client_for(customer).post(URL, {"message": EXAMPLE}, format="json").data["conversation_id"]
    assert client_for(customer).get(f"/api/v1/assistant/conversations/{conv}/").status_code == 200
    assert api.get(f"/api/v1/assistant/conversations/{conv}/").status_code == 404
    assert Message.objects.count() == 2


def test_message_length_limit(api):
    assert api.post(URL, {"message": "x" * 501}, format="json").status_code == 400


def _mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_gemini_adapter_parses_usage_and_maps_errors():
    def ok(request):
        body = json.loads(request.content)
        assert request.headers["x-goog-api-key"] == "k" and body["generationConfig"]["maxOutputTokens"] == 100
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}],
                                         "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3}})
    result = GeminiProvider(api_key="k", model="m", timeout=1, client=_mock_client(ok)).complete_json(system="s", user="u", max_tokens=100)
    assert result.text == "{}" and result.tokens_in == 12
    limited = GeminiProvider(api_key="k", model="m", timeout=1, client=_mock_client(lambda r: httpx.Response(429, headers={"retry-after": "7"})))
    with pytest.raises(RateLimited) as exc:
        limited.complete_json(system="s", user="u", max_tokens=10)
    assert exc.value.retry_after == 7


def test_groq_adapter_and_server_error():
    def ok(request):
        assert request.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"intent\":\"search\"}"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}})
    assert GroqProvider(api_key="k", model="m", timeout=1, client=_mock_client(ok)).complete_json(system="s", user="u", max_tokens=10).tokens_out == 2
    with pytest.raises(ServerError):
        GroqProvider(api_key="k", model="m", timeout=1, client=_mock_client(lambda r: httpx.Response(503))).complete_json(system="s", user="u", max_tokens=10)


def test_no_api_key_means_rules_provider():
    from apps.assistant.providers import get_provider

    with override_settings(LLM_PROVIDER="gemini", LLM_API_KEY="", LLM_MODEL="x"):
        assert get_provider() is None


def test_rules_mode_does_not_consume_llm_quota(api, catalog):
    api.post(URL, {"message": EXAMPLE}, format="json")
    usage = DailyUsage.objects.get(scope="global")
    assert usage.requests == 1 and usage.llm_requests == 0 and usage.provider_calls == 0
