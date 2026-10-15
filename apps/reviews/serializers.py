from rest_framework import serializers

from .models import Review


class ReviewSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.public_name", read_only=True)

    class Meta:
        model = Review
        fields = ["id", "rating", "owner_rating", "comment", "author_name", "created_at"]


class ReviewCreateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    owner_rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class AdminReviewSerializer(ReviewSerializer):
    listing_title = serializers.CharField(source="listing.title", read_only=True)

    class Meta(ReviewSerializer.Meta):
        fields = ReviewSerializer.Meta.fields + ["status", "moderation_note", "listing", "listing_title"]


class ReviewModerationSerializer(serializers.Serializer):
    hide = serializers.BooleanField()
    note = serializers.CharField(max_length=300)
