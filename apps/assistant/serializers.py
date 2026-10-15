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
    alternatives = ListingCardSerializer(many=True)
    mode = serializers.ChoiceField(choices=["llm", "rules", "fallback"])
    remaining_today = serializers.IntegerField()


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "text", "criteria", "listing_ids", "mode", "created_at"]
