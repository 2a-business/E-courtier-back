from decimal import ROUND_HALF_UP, Decimal

from rest_framework import serializers

from apps.accounts.serializers import PublicUserSerializer

from .models import Amenity, Listing, ListingPhoto

VERIFIED_LABEL = "Annonce vérifiée"
VERIFIED_DISCLAIMER = (
    "Les justificatifs fournis (identité, titre ou mandat) ont été examinés par l'équipe E-Courtier. "
    "Cet examen réduit les risques mais ne constitue ni une authentification officielle des documents "
    "ni une garantie juridique de propriété."
)


def approx(value):
    """Coordonnée arrondie à ~110 m pour ne pas révéler l'adresse exacte."""
    if value is None:
        return None
    return float(Decimal(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


class AmenitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Amenity
        fields = ["slug", "label"]


class PhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingPhoto
        fields = ["id", "image", "thumbnail", "width", "height", "caption", "position", "is_primary"]
        read_only_fields = fields


class ListingCardSerializer(serializers.ModelSerializer):
    """Représentation légère pour les listes, la carte et l'assistant."""

    cover = serializers.SerializerMethodField()
    is_verified = serializers.BooleanField(read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    property_type_label = serializers.CharField(source="get_property_type_display", read_only=True)

    class Meta:
        model = Listing
        fields = [
            "id", "title", "property_type", "property_type_label", "transaction_type", "price", "currency",
            "surface_m2", "rooms", "bedrooms", "bathrooms", "is_furnished", "city", "district",
            "latitude", "longitude", "is_verified", "is_featured", "is_demo", "cover", "published_at",
        ]

    def get_cover(self, obj) -> str | None:
        photos = list(obj.photos.all())
        if not photos:
            return None
        request = self.context.get("request")
        photo = photos[0]
        url = (photo.thumbnail or photo.image).url
        return request.build_absolute_uri(url) if request else url

    def get_latitude(self, obj) -> float | None:
        return approx(obj.latitude)

    def get_longitude(self, obj) -> float | None:
        return approx(obj.longitude)


class ListingDetailSerializer(ListingCardSerializer):
    photos = PhotoSerializer(many=True, read_only=True)
    amenities = AmenitySerializer(many=True, read_only=True)
    owner = PublicUserSerializer(read_only=True)
    address_private = serializers.SerializerMethodField()
    verification = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    can_manage = serializers.SerializerMethodField()

    class Meta(ListingCardSerializer.Meta):
        fields = ListingCardSerializer.Meta.fields + [
            "description", "address_public", "address_private", "amenities", "photos", "owner",
            "publication_status", "verification_status", "verification", "rating", "can_manage",
            "created_at", "updated_at",
        ]

    def get_address_private(self, obj) -> str | None:
        return obj.address_private if self.context.get("can_see_address") else None

    def get_verification(self, obj) -> dict:
        if obj.is_verified:
            return {"label": VERIFIED_LABEL, "disclaimer": VERIFIED_DISCLAIMER}
        return {"label": None, "disclaimer": None}

    def get_rating(self, obj) -> dict:
        avg = getattr(obj, "rating_avg", None)
        return {"average": round(avg, 1) if avg else None, "count": getattr(obj, "rating_count", 0)}

    def get_can_manage(self, obj) -> bool:
        user = self.context.get("request").user if self.context.get("request") else None
        return bool(user and user.is_authenticated and (user.is_admin or obj.owner_id == user.pk))


class OwnerListingSerializer(ListingCardSerializer):
    visits_pending = serializers.IntegerField(read_only=True, default=0)
    reports_open = serializers.IntegerField(read_only=True, default=0)

    class Meta(ListingCardSerializer.Meta):
        fields = ListingCardSerializer.Meta.fields + [
            "publication_status", "verification_status", "visits_pending", "reports_open", "created_at",
        ]


class ListingWriteSerializer(serializers.ModelSerializer):
    amenities = serializers.ListField(child=serializers.SlugField(), required=False)

    class Meta:
        model = Listing
        fields = [
            "title", "description", "property_type", "transaction_type", "price", "surface_m2", "rooms",
            "bedrooms", "bathrooms", "is_furnished", "city", "district", "address_private", "address_public",
            "latitude", "longitude", "amenities",
        ]

    def validate(self, attrs):
        lat = attrs.get("latitude", getattr(self.instance, "latitude", None))
        lng = attrs.get("longitude", getattr(self.instance, "longitude", None))
        if (lat is None) != (lng is None):
            raise serializers.ValidationError({"latitude": "Latitude et longitude doivent être fournies ensemble."})
        bedrooms = attrs.get("bedrooms", getattr(self.instance, "bedrooms", 0))
        rooms = attrs.get("rooms", getattr(self.instance, "rooms", 1))
        if bedrooms > rooms:
            raise serializers.ValidationError({"bedrooms": "Le nombre de chambres ne peut dépasser le nombre de pièces."})
        return attrs


class PublicationSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["DRAFT", "PUBLISHED", "ARCHIVED"])


class PhotoUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()
    caption = serializers.CharField(max_length=80, required=False, allow_blank=True)


class PhotoReorderSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)


class ModerationActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["suspend", "restore"])
    reason = serializers.CharField(max_length=300)


class FeaturedSerializer(serializers.Serializer):
    featured = serializers.BooleanField()
