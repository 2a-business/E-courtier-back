from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.listings.models import PropertyType, TransactionType

ORDERING_CHOICES = ["newest", "price_asc", "price_desc", "surface_desc", "distance"]


@extend_schema_field(OpenApiTypes.STR)
class CommaListField(serializers.Field):
    """Liste séparée par des virgules : « APARTMENT,STUDIO »."""

    def __init__(self, choices=None, **kwargs):
        self.choices = choices
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        items = data if isinstance(data, list) else str(data).split(",")
        items = [i.strip() for i in items if str(i).strip()]
        if self.choices:
            invalid = [i for i in items if i not in self.choices]
            if invalid:
                raise serializers.ValidationError(f"Valeurs invalides : {', '.join(invalid)}")
        return items

    def to_representation(self, value):
        return value


class SearchParamsSerializer(serializers.Serializer):
    """Critères de recherche validés. Sert aussi de schéma de validation pour l'assistant IA."""

    transaction_type = serializers.ChoiceField(choices=TransactionType.choices, required=False)
    property_type = CommaListField(choices=PropertyType.values, required=False)
    price_min = serializers.IntegerField(min_value=0, required=False)
    price_max = serializers.IntegerField(min_value=0, required=False)
    surface_min = serializers.IntegerField(min_value=0, required=False)
    surface_max = serializers.IntegerField(min_value=0, required=False)
    rooms_min = serializers.IntegerField(min_value=0, max_value=50, required=False)
    rooms_max = serializers.IntegerField(min_value=0, max_value=50, required=False)
    bedrooms_min = serializers.IntegerField(min_value=0, max_value=50, required=False)
    city = serializers.CharField(max_length=80, required=False)
    district = serializers.CharField(max_length=80, required=False)
    amenities = CommaListField(required=False)
    furnished = serializers.BooleanField(required=False, allow_null=True, default=None)
    verified = serializers.BooleanField(required=False, default=False)
    featured = serializers.BooleanField(required=False, default=False)
    q = serializers.CharField(max_length=100, required=False)
    near_lat = serializers.FloatField(min_value=12.0, max_value=16.8, required=False)
    near_lng = serializers.FloatField(min_value=-17.6, max_value=-11.3, required=False)
    radius_km = serializers.FloatField(min_value=0.2, max_value=50, required=False, default=3)
    ordering = serializers.ChoiceField(choices=ORDERING_CHOICES, required=False, default="newest")

    def validate(self, attrs):
        if attrs.get("price_min") and attrs.get("price_max") and attrs["price_min"] > attrs["price_max"]:
            raise serializers.ValidationError({"price_max": "Le prix maximum doit être supérieur au minimum."})
        if (attrs.get("near_lat") is None) != (attrs.get("near_lng") is None):
            raise serializers.ValidationError({"near_lat": "Latitude et longitude vont ensemble."})
        if attrs.get("ordering") == "distance" and attrs.get("near_lat") is None:
            attrs["ordering"] = "newest"
        return attrs
