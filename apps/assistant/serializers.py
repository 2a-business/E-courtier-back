from rest_framework import serializers

from apps.listings.serializers import ListingCardSerializer

from .models import Message


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=500, trim_whitespace=True)
    conversation_id = serializers.UUIDField(required=False, allow_null=True)


class ChatResponseSerializer(serializers.Serializer):
    conversation_id = serializers.UUIDField()
    reply = serializers.CharField()
    criteria = serializers.DictField()
    results = ListingCardSerializer(many=True)
    total = serializers.IntegerField(help_text="Nombre total d'annonces publiées correspondant exactement (au-delà de celles affichées).")
    alternatives = ListingCardSerializer(many=True)
    relaxed = serializers.ListField(child=serializers.CharField(), help_text="Critères élargis pour obtenir les alternatives.")
    mode = serializers.ChoiceField(choices=["llm", "rules", "fallback"])
    remaining_today = serializers.IntegerField()


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "text", "criteria", "listing_ids", "mode", "created_at"]
