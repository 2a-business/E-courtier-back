"""Recherche exacte dans PostgreSQL. L'assistant IA n'y accède qu'au travers de cette fonction."""

import math

from django.db.models import Count, ExpressionWrapper, F, FloatField, Q, Value
from django.db.models.functions import Cast

from apps.listings.models import VerificationStatus
from apps.listings.selectors import card_queryset
from apps.listings.text import normalize

KM_PER_DEGREE_LAT = 111.32


def search_listings(params: dict):
    qs = card_queryset()

    if params.get("transaction_type"):
        qs = qs.filter(transaction_type=params["transaction_type"])
    if params.get("property_type"):
        qs = qs.filter(property_type__in=params["property_type"])
    if params.get("price_min") is not None:
        qs = qs.filter(price__gte=params["price_min"])
    if params.get("price_max") is not None:
        qs = qs.filter(price__lte=params["price_max"])
    if params.get("surface_min") is not None:
        qs = qs.filter(surface_m2__gte=params["surface_min"])
    if params.get("surface_max") is not None:
        qs = qs.filter(surface_m2__lte=params["surface_max"])
    if params.get("rooms_min") is not None:
        qs = qs.filter(rooms__gte=params["rooms_min"])
    if params.get("rooms_max") is not None:
        qs = qs.filter(rooms__lte=params["rooms_max"])
    if params.get("bedrooms_min") is not None:
        qs = qs.filter(bedrooms__gte=params["bedrooms_min"])
    if params.get("city"):
        qs = qs.filter(city_normalized__contains=normalize(params["city"]))
    if params.get("district"):
        qs = qs.filter(district_normalized__contains=normalize(params["district"]))
    if params.get("furnished") is not None:
        qs = qs.filter(is_furnished=params["furnished"])
    if params.get("verified"):
        qs = qs.filter(verification_status=VerificationStatus.APPROVED)
    if params.get("featured"):
        qs = qs.filter(is_featured=True)
    if params.get("q"):
        qs = qs.filter(Q(title__icontains=params["q"]) | Q(description__icontains=params["q"]))
    amenities = params.get("amenities") or []
    if amenities:
        # Toutes les commodités demandées doivent être présentes.
        qs = qs.filter(amenities__slug__in=amenities).annotate(
            matched=Count("amenities", filter=Q(amenities__slug__in=amenities), distinct=True)
        ).filter(matched=len(set(amenities)))

    lat, lng = params.get("near_lat"), params.get("near_lng")
    if lat is not None and lng is not None:
        radius = params.get("radius_km") or 3
        dlat = radius / KM_PER_DEGREE_LAT
        cos_lat = math.cos(math.radians(lat))
        dlng = radius / (KM_PER_DEGREE_LAT * cos_lat)
        qs = qs.filter(
            latitude__isnull=False,
            latitude__range=(lat - dlat, lat + dlat),
            longitude__range=(lng - dlng, lng + dlng),
        )
        # Distance approchée (projection équirectangulaire), suffisante pour un tri à l'échelle d'une ville.
        qs = qs.annotate(
            distance_sq=ExpressionWrapper(
                (Cast("latitude", FloatField()) - Value(lat)) * (Cast("latitude", FloatField()) - Value(lat))
                + (Cast("longitude", FloatField()) - Value(lng))
                * (Cast("longitude", FloatField()) - Value(lng))
                * Value(cos_lat * cos_lat),
                output_field=FloatField(),
            )
        )

    ordering = {
        "newest": ["-published_at", "-created_at"],
        "price_asc": ["price", "-published_at"],
        "price_desc": ["-price", "-published_at"],
        "surface_desc": [F("surface_m2").desc(nulls_last=True), "-published_at"],
        "distance": ["distance_sq", "-published_at"],
    }[params.get("ordering") or "newest"]
    return qs.order_by(*ordering).distinct() if amenities else qs.order_by(*ordering)


def locations():
    from apps.listings.selectors import public_listings

    rows = public_listings().values_list("city", "district").annotate(n=Count("id")).order_by("city", "district")
    result: dict[str, list] = {}
    for city, district, n in rows:
        result.setdefault(city, []).append({"district": district, "count": n})
    return [{"city": c, "districts": d} for c, d in result.items()]
