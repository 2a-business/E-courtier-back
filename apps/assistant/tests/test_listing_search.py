"""L'assistant retrouve les annonces réellement publiées — reproduction du bug de production et non-régression.

Bug constaté en production (2026-10-20) : « donne-moi les apparts du site web » → « Aucune annonce … appartement »
alors qu'une annonce intitulée « Appartement a Kenya » était publiée : elle est classée VILLA par l'annonceur
et la recherche filtrait strictement sur le type, y compris pour les alternatives.
"""

import json
import re

import pytest
from django.db import DatabaseError

from apps.assistant import finder, services
from apps.assistant.models import Message
from apps.assistant.providers.base import ServerError, Timeout
from apps.listings.models import PublicationStatus
from conftest import make_listing

from .test_assistant import FakeProvider, use

pytestmark = pytest.mark.django_db
URL = "/api/v1/assistant/chat/"


@pytest.fixture
def kenya(owner):
    return make_listing(owner, title="Appartement à Kenya", property_type="APARTMENT", price=120_000, rooms=3,
                        city="Ziguinchor", district="Kenia")


@pytest.fixture
def kenya_as_villa(owner):
    """Copie fidèle de la donnée de production : titre « Appartement », type VILLA, 1 200 000 FCFA."""
    return make_listing(owner, title="Appartement a Kenya", property_type="VILLA", price=1_200_000, rooms=6,
                        city="Ziguinchor", district="Kenia")


def ask(api, message, conversation_id=None):
    res = api.post(URL, {"message": message, "conversation_id": conversation_id}, format="json")
    assert res.status_code == 200, res.data
    return res.data


def titles(items):
    return [item["title"] for item in items]


# 1 ------------------------------------------------------------------------------------------------


def test_generic_request_finds_the_apartment(api, kenya):
    data = ask(api, "donne-moi les apparts du site web")
    assert titles(data["results"]) == ["Appartement à Kenya"] and data["total"] == 1
    assert data["results"][0]["id"] == str(kenya.pk) and data["results"][0]["price"] == 120_000
    assert data["reply"] == "J'ai trouvé 1 annonce publiée pour : appartement."


def test_production_case_listing_classified_as_villa_is_found_with_honest_note(api, kenya_as_villa):
    data = ask(api, "donne-moi les apparts du site web")
    assert titles(data["results"]) == ["Appartement a Kenya"]
    assert "classée « Villa » par l'annonceur" in data["reply"] and "Aucune annonce" not in data["reply"]


def test_exact_type_ranks_before_title_only_match(api, kenya, kenya_as_villa):
    data = ask(api, "je cherche un appartement")
    assert [r["id"] for r in data["results"]] == [str(kenya.pk), str(kenya_as_villa.pk)]


def test_catalogue_request_without_criteria_lists_published_listings(api, kenya, owner):
    make_listing(owner, title="Villa Saly", property_type="VILLA", price=500_000, city="Saly", district="Saly Portudal")
    data = ask(api, "montre-moi toutes les annonces du site")
    assert set(titles(data["results"])) == {"Appartement à Kenya", "Villa Saly"} and data["total"] == 2


# 2 ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "je veux louer à Ziguinchor pour moins de 150 000 FCFA",
    "location ziguinchor max 150k",
    "un appart à louer à Kenya, budget 150 000",  # « Kenya » : orthographe proche du quartier réel « Kenia »
])
def test_rent_under_150k_in_ziguinchor(api, kenya, owner, message):
    make_listing(owner, title="Appartement Dakar", price=100_000, city="Dakar", district="Mermoz")
    data = ask(api, message)
    assert titles(data["results"]) == ["Appartement à Kenya"]


# 3 ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "APPARTEMENT À ZIGUINCHOR",
    "appartemnt a ziguinchor",       # faute de frappe
    "apartement ziginchor",          # deux fautes
    "un appt à louer vers ziguinchor",
    "Appartements à Ziguinchor",
])
def test_synonyms_typos_case_and_accents(api, kenya, message):
    assert titles(ask(api, message)["results"]) == ["Appartement à Kenya"]


def test_accented_city_and_room_synonym(api, owner):
    make_listing(owner, title="Chambre meublée étudiant", property_type="ROOM", price=60_000, city="Thiès", district="Randoulène")
    make_listing(owner, title="Maison familiale", property_type="HOUSE", price=300_000, city="Thies", district="Grand Thiès")
    assert titles(ask(api, "chambre à louer à thies")["results"]) == ["Chambre meublée étudiant"]
    assert titles(ask(api, "une maison à Thiès")["results"]) == ["Maison familiale"]


# 4 ------------------------------------------------------------------------------------------------


def test_budget_too_low_gives_no_false_result(api, kenya):
    data = ask(api, "appart à louer à Ziguinchor moins de 50 000 FCFA")
    assert data["results"] == [] and data["alternatives"] == []
    assert "Aucune annonce publiée ne correspond" in data["reply"]
    assert "la moins chère actuellement publiée est à 120 000 FCFA" in data["reply"]


def test_alternatives_stay_within_announced_relaxation(api, kenya):
    data = ask(api, "appart à louer à Ziguinchor moins de 100 000 FCFA")
    assert data["results"] == [] and titles(data["alternatives"]) == ["Appartement à Kenya"]
    assert "budget augmenté de 20 %" in data["reply"] and data["relaxed"] == ["budget augmenté de 20 %"]
    assert all(a["price"] <= 120_000 for a in data["alternatives"])


# 5 ------------------------------------------------------------------------------------------------


def test_unpublished_listings_are_never_revealed(api, owner, kenya):
    make_listing(owner, title="Appartement brouillon secret", city="Ziguinchor", district="Kenia", price=90_000, publish=False)
    archived = make_listing(owner, title="Appartement archivé secret", city="Ziguinchor", district="Kenia", price=95_000)
    archived.publication_status = PublicationStatus.ARCHIVED
    archived.save(update_fields=["publication_status"])
    for message in ("donne-moi les apparts du site web", "appart Ziguinchor moins de 100 000", "toutes les annonces"):
        data = ask(api, message)
        shown = titles(data["results"]) + titles(data["alternatives"])
        assert not any("secret" in t for t in shown) and "secret" not in data["reply"]


# 6 ------------------------------------------------------------------------------------------------


def test_empty_database_gives_honest_answer_without_alternatives(api, db):
    data = ask(api, "donne-moi les apparts du site web")
    assert data["results"] == [] and data["alternatives"] == [] and data["total"] == 0
    assert "Aucune annonce publiée ne correspond" in data["reply"] and "même en élargissant" in data["reply"]


def test_no_exact_match_proposes_real_nearby_listings(api, owner):
    villa = make_listing(owner, title="Villa Cap Skirring", property_type="VILLA", price=400_000, city="Ziguinchor", district="Cap Skirring")
    data = ask(api, "studio à Ziguinchor")
    assert data["results"] == [] and [a["id"] for a in data["alternatives"]] == [str(villa.pk)]
    assert "Aucune annonce publiée ne correspond exactement à : studio, à Ziguinchor." in data["reply"]
    assert "tous types de biens" in data["reply"]
    # Une villa proposée après élargissement du type n'est pas présentée comme un « studio » mal classé.
    assert "Remarque" not in data["reply"] and "évoque" not in data["reply"]


# 7 ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("error", [ServerError("503", http_status=503), Timeout("délai")])
def test_search_still_works_when_gemini_is_down(api, kenya, monkeypatch, error):
    use(monkeypatch, FakeProvider(error, error))
    data = ask(api, "donne-moi les apparts du site web")
    assert data["mode"] == "fallback" and titles(data["results"]) == ["Appartement à Kenya"]
    assert "Assistant IA momentanément indisponible" in data["reply"]


def test_gemini_criteria_use_the_database_as_source_of_truth(api, kenya_as_villa, monkeypatch):
    # Gemini comprend « appartement » ; la base décide de l'existence (annonce classée VILLA retrouvée et signalée).
    use(monkeypatch, FakeProvider(json.dumps({"intent": "search", "property_type": ["APARTMENT"]})))
    data = ask(api, "donne-moi les apparts du site web")
    assert data["mode"] == "llm" and titles(data["results"]) == ["Appartement a Kenya"]


def test_gemini_empty_extraction_is_completed_by_rules(api, kenya, monkeypatch):
    use(monkeypatch, FakeProvider(json.dumps({"intent": "other"})))
    data = ask(api, "appart à Ziguinchor")
    assert data["mode"] == "llm" and titles(data["results"]) == ["Appartement à Kenya"]
    assert data["criteria"]["city"] == "Ziguinchor"


def test_gemini_misspelled_place_is_mapped_to_real_one(api, kenya, monkeypatch):
    use(monkeypatch, FakeProvider(json.dumps({"intent": "search", "district": "Kenya"})))
    data = ask(api, "à Kenya")
    assert data["criteria"]["district"] == "Kenia" and titles(data["results"]) == ["Appartement à Kenya"]


# 8 ------------------------------------------------------------------------------------------------


def test_database_error_is_not_presented_as_no_results(api, kenya, monkeypatch):
    def broken(*args, **kwargs):
        raise DatabaseError("connexion perdue")

    monkeypatch.setattr(finder, "find", broken)
    res = api.post(URL, {"message": "donne-moi les apparts du site web"}, format="json")
    assert res.status_code == 503 and res.data["code"] == "search_unavailable"
    assert "ne signifie pas qu'aucune annonce ne correspond" in res.data["detail"]
    assert not Message.objects.filter(role="assistant").exists()


# 10 et conversation --------------------------------------------------------------------------------


def test_total_count_beyond_display_limit(api, owner, settings):
    settings.ASSISTANT_RESULTS_LIMIT = 3
    for i in range(5):
        make_listing(owner, title=f"Appartement Ziguinchor {i}", price=100_000 + i, city="Ziguinchor", district="Boucotte")
    data = ask(api, "apparts à Ziguinchor")
    assert data["total"] == 5 and len(data["results"]) == 3
    assert "J'ai trouvé 5 annonces publiées" in data["reply"] and "Voici les 3 plus pertinentes" in data["reply"]


def test_context_is_kept_while_refining(api, kenya, owner):
    make_listing(owner, title="Appartement Ziguinchor haut de gamme", price=400_000, city="Ziguinchor", district="Boucotte")
    first = ask(api, "appart à Ziguinchor")
    assert len(first["results"]) == 2
    second = ask(api, "moins de 150 000", first["conversation_id"])
    assert titles(second["results"]) == ["Appartement à Kenya"] and second["criteria"]["city"] == "Ziguinchor"


def test_comparison_uses_only_real_listing_data(api, kenya, owner):
    other = make_listing(owner, title="Appartement Boucotte", price=180_000, rooms=4, city="Ziguinchor", district="Boucotte")
    first = ask(api, "apparts à Ziguinchor")
    data = ask(api, "compare-les", first["conversation_id"])
    assert {r["id"] for r in data["results"]} == {str(kenya.pk), str(other.pk)}
    assert "120 000 FCFA / mois" in data["reply"] and "180 000 FCFA / mois" in data["reply"]
    assert "La moins chère : « Appartement à Kenya »" in data["reply"]
    # Aucun montant cité qui n'existe pas dans les annonces.
    amounts = {int(a.replace(" ", "")) for a in re.findall(r"(\d{1,3}(?: \d{3})+) FCFA", data["reply"])}
    assert amounts <= {kenya.price, other.price}


def test_replies_contain_only_real_listings_and_prices(api, kenya):
    data = ask(api, "donne-moi les apparts du site web")
    for card in data["results"]:
        assert card["id"] == str(kenya.pk) and card["price"] == kenya.price and card["city"] == "Ziguinchor"
    amounts = {int(a.replace(" ", "")) for a in re.findall(r"(\d{1,3}(?: \d{3})+) FCFA", data["reply"])}
    assert amounts <= {kenya.price}


def test_ambiguous_transaction_asks_for_precision(api, kenya):
    data = ask(api, "louer ou acheter un appart à Ziguinchor")
    assert data["criteria"]["transaction_type"] is None and "Souhaitez-vous louer ou acheter" in data["reply"]
    assert titles(data["results"]) == ["Appartement à Kenya"]


def test_greeting_still_answers_with_help(api, kenya):
    data = ask(api, "bonjour")
    assert data["results"] == [] and "Exemple" in data["reply"]


def test_services_module_exposes_search_error_type():
    assert services.SearchUnavailable().http_status == 503
