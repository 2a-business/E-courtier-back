import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .text import normalize


class PropertyType(models.TextChoices):
    APARTMENT = "APARTMENT", "Appartement"
    HOUSE = "HOUSE", "Maison"
    VILLA = "VILLA", "Villa"
    STUDIO = "STUDIO", "Studio"
    ROOM = "ROOM", "Chambre"
    LAND = "LAND", "Terrain"
    OFFICE = "OFFICE", "Bureau / local"


class TransactionType(models.TextChoices):
    RENT = "RENT", "Location"
    SALE = "SALE", "Vente"


class PublicationStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    PUBLISHED = "PUBLISHED", "Publiée"
    ARCHIVED = "ARCHIVED", "Archivée"
    SUSPENDED = "SUSPENDED", "Suspendue par la modération"


class VerificationStatus(models.TextChoices):
    NOT_SUBMITTED = "NOT_SUBMITTED", "Non soumise"
    PENDING = "PENDING", "En cours d'examen"
    APPROVED = "APPROVED", "Vérifiée"
    REJECTED = "REJECTED", "Refusée"


class Amenity(models.Model):
    slug = models.SlugField(max_length=40, unique=True)
    label = models.CharField(max_length=60)
    # Synonymes séparés par des virgules, utilisés par l'assistant (« clim, climatiseur »).
    synonyms = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["label"]
        verbose_name = "équipement"

    def __str__(self):
        return self.label


class Listing(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="listings")
    title = models.CharField("titre", max_length=120)
    description = models.TextField(max_length=5000)
    property_type = models.CharField(max_length=10, choices=PropertyType.choices)
    transaction_type = models.CharField(max_length=4, choices=TransactionType.choices)
    price = models.PositiveBigIntegerField("prix (FCFA)", validators=[MinValueValidator(1000)])
    currency = models.CharField(max_length=3, default="XOF", editable=False)
    surface_m2 = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(5), MaxValueValidator(100000)])
    rooms = models.PositiveSmallIntegerField("pièces", default=1, validators=[MaxValueValidator(50)])
    bedrooms = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(50)])
    bathrooms = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(50)])
    is_furnished = models.BooleanField("meublé", default=False)
    city = models.CharField(max_length=80)
    district = models.CharField("quartier", max_length=80)
    city_normalized = models.CharField(max_length=80, editable=False, db_index=True)
    district_normalized = models.CharField(max_length=80, editable=False, db_index=True)
    # Adresse exacte : visible uniquement par le responsable, l'admin et les clients ayant une visite confirmée.
    address_private = models.CharField("adresse exacte", max_length=200, blank=True)
    # Indication publique (« Près du marché de Fann »).
    address_public = models.CharField("repère public", max_length=200, blank=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal("12.0")), MaxValueValidator(Decimal("16.8"))],
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal("-17.6")), MaxValueValidator(Decimal("-11.3"))],
    )
    amenities = models.ManyToManyField(Amenity, blank=True, related_name="listings")
    publication_status = models.CharField(
        max_length=10, choices=PublicationStatus.choices, default=PublicationStatus.DRAFT, db_index=True
    )
    # Modifié exclusivement par apps.verification.services.
    verification_status = models.CharField(
        max_length=14, choices=VerificationStatus.choices, default=VerificationStatus.NOT_SUBMITTED, editable=False
    )
    is_featured = models.BooleanField("à la une", default=False)
    is_demo = models.BooleanField("donnée de démonstration", default=False, editable=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        verbose_name = "logement"
        indexes = [
            models.Index(fields=["publication_status", "transaction_type", "property_type", "price"]),
            models.Index(fields=["publication_status", "verification_status"]),
            models.Index(fields=["publication_status", "district_normalized"]),
            models.Index(fields=["latitude", "longitude"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gte=1000), name="listing_price_min"),
            models.CheckConstraint(condition=models.Q(currency="XOF"), name="listing_currency_xof"),
            models.CheckConstraint(
                condition=(models.Q(latitude__isnull=True) & models.Q(longitude__isnull=True))
                | (models.Q(latitude__isnull=False) & models.Q(longitude__isnull=False)),
                name="listing_coordinates_complete",
            ),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.city_normalized = normalize(self.city)
        self.district_normalized = normalize(self.district)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and ({"city", "district"} & set(update_fields)):
            kwargs["update_fields"] = set(update_fields) | {"city_normalized", "district_normalized"}
        super().save(*args, **kwargs)

    @property
    def is_verified(self) -> bool:
        return self.verification_status == VerificationStatus.APPROVED

    @property
    def is_public(self) -> bool:
        return self.publication_status == PublicationStatus.PUBLISHED


def listing_photo_path(instance, filename):
    return f"listings/{instance.listing_id}/{uuid.uuid4().hex}.jpg"


class ListingPhoto(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to=listing_photo_path, width_field="width", height_field="height")
    thumbnail = models.ImageField(upload_to=listing_photo_path, blank=True)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    caption = models.CharField(max_length=80, blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["listing"], condition=models.Q(is_primary=True), name="one_primary_photo_per_listing"
            )
        ]
