from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class ReviewStatus(models.TextChoices):
    PUBLISHED = "PUBLISHED", "Publié"
    HIDDEN = "HIDDEN", "Masqué par la modération"


class Review(models.Model):
    listing = models.ForeignKey("listings.Listing", on_delete=models.CASCADE, related_name="reviews")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    # Note du logement et de l'accueil du propriétaire / agent (1 à 5).
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    owner_rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(max_length=1000, blank=True)
    status = models.CharField(max_length=10, choices=ReviewStatus.choices, default=ReviewStatus.PUBLISHED, db_index=True)
    moderation_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["listing", "author"], name="one_review_per_author_listing"),
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name="review_rating_range"),
            models.CheckConstraint(condition=models.Q(owner_rating__gte=1, owner_rating__lte=5), name="review_owner_rating_range"),
        ]
