import pytest

from conftest import make_listing

pytestmark = pytest.mark.django_db
URL = "/api/v1/search/listings/"


@pytest.fixture
def catalog(owner):
    a = make_listing(owner, title="A", price=200000, rooms=2, district="Mermoz", amenities=["balcon"])
    b = make_listing(owner, title="B", price=300000, rooms=3, district="Fann-Hock", amenities=["balcon", "climatisation"])
    c = make_listing(owner, title="C", price=90000000, transaction_type="SALE", property_type="VILLA", rooms=6,
                     district="Almadies", latitude="14.744700", longitude="-17.510800")
    make_listing(owner, title="Brouillon", publish=False)
    return a, b, c


def titles(res):
    return [r["title"] for r in res.data["results"]]


def test_drafts_never_listed(api, catalog):
    assert api.get(URL).data["count"] == 3


def test_exact_filters(api, catalog):
    assert titles(api.get(URL, {"transaction_type": "RENT", "price_max": 250000})) == ["A"]
    assert titles(api.get(URL, {"district": "fann hock"})) == ["B"]  # accents / tirets normalisés
    assert titles(api.get(URL, {"property_type": "VILLA,HOUSE"})) == ["C"]
    assert titles(api.get(URL, {"rooms_min": 3, "rooms_max": 3})) == ["B"]


def test_amenities_must_all_match(api, catalog):
    assert titles(api.get(URL, {"amenities": "balcon"})) and sorted(titles(api.get(URL, {"amenities": "balcon"}))) == ["A", "B"]
    assert titles(api.get(URL, {"amenities": "balcon,climatisation"})) == ["B"]


def test_ordering_and_pagination(api, catalog):
    assert titles(api.get(URL, {"ordering": "price_asc"})) == ["A", "B", "C"]
    res = api.get(URL, {"ordering": "price_desc", "page_size": 1, "page": 2})
    assert titles(res) == ["B"] and res.data["count"] == 3 and res.data["next"]


def test_proximity(api, catalog):
    res = api.get(URL, {"near_lat": 14.7447, "near_lng": -17.5108, "radius_km": 1, "ordering": "distance"})
    assert titles(res) == ["C"]


def test_verified_filter(api, catalog):
    assert api.get(URL, {"verified": "true"}).data["count"] == 0


def test_invalid_params(api, catalog):
    res = api.get(URL, {"price_min": 500, "price_max": 100})
    assert res.status_code == 400 and res.data["code"] == "validation_error"
    assert api.get(URL, {"property_type": "CHATEAU"}).status_code == 400


def test_locations(api, catalog):
    data = api.get("/api/v1/search/locations/").data
    assert data[0]["city"] == "Dakar" and len(data[0]["districts"]) == 3
