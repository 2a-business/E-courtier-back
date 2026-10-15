from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminRole
from apps.listings.models import Listing
from apps.listings.selectors import card_queryset
from apps.listings.serializers import ListingCardSerializer

from . import quota, services
from .models import LLMCallLog
from .providers import get_provider
from .serializers import ChatRequestSerializer, ChatResponseSerializer, MessageSerializer

SUGGESTIONS = [
    "Appartement 3 pièces à louer à Fann Hock, moins de 300 000 FCFA, avec balcon",
    "Studio meublé à Mermoz jusqu'à 150 000 FCFA par mois",
    "Villa à vendre aux Almadies avec piscine",
    "Chambre à louer à Ouakam pour étudiant",
]


class ChatView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "assistant"

    @extend_schema(request=ChatRequestSerializer, responses={200: ChatResponseSerializer}, tags=["assistant"])
    def post(self, request):
        s = ChatRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        result = services.handle_message(
            user=request.user, anon_key=services.anon_key_for(request), text=s.validated_data["message"],
            conversation_id=s.validated_data.get("conversation_id"),
        )
        ctx = {"request": request}
        result["results"] = ListingCardSerializer(result["results"], many=True, context=ctx).data
        result["alternatives"] = ListingCardSerializer(result["alternatives"], many=True, context=ctx).data
        return Response(result)


class ConversationView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses={200: None}, tags=["assistant"])
    def get(self, request, pk):
        conversation = services.get_conversation(pk, request.user, services.anon_key_for(request))
        if not conversation:
            return Response({"code": "not_found", "detail": "Conversation introuvable."}, status=404)
        messages = list(conversation.messages.order_by("-created_at")[:30])[::-1]
        ids = {i for m in messages for i in m.listing_ids}
        listings = card_queryset(Listing.objects.filter(pk__in=ids, publication_status="PUBLISHED"))
        return Response({
            "conversation_id": str(conversation.pk),
            "messages": MessageSerializer(messages, many=True).data,
            # Seules les annonces encore publiées sont renvoyées.
            "listings": ListingCardSerializer(listings, many=True, context={"request": request}).data,
        })


class AssistantInfoView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses={200: None}, tags=["assistant"])
    def get(self, request):
        provider = get_provider()
        return Response({
            "llm_enabled": provider is not None,
            "max_message_chars": settings.ASSISTANT_MAX_MESSAGE_CHARS,
            "suggestions": SUGGESTIONS,
        })


class AssistantUsageView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request):
        last = LLMCallLog.objects.order_by("-created_at")[:200]
        latencies = sorted(c.latency_ms for c in last if c.status == "ok")
        return Response({
            **quota.today_usage(),
            "provider": settings.LLM_PROVIDER,
            "model": settings.LLM_MODEL,
            "recent_calls": len(last),
            "recent_errors": sum(1 for c in last if c.status != "ok"),
            "latency_p50_ms": latencies[len(latencies) // 2] if latencies else None,
            "latency_p95_ms": latencies[int(len(latencies) * 0.95) - 1] if len(latencies) >= 20 else None,
        })
