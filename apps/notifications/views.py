from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Notification
from .serializers import MarkReadSerializer, NotificationSerializer


@extend_schema(tags=["notifications"])
class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        qs = Notification.objects.filter(user=self.request.user)
        if self.request.query_params.get("unread") == "true":
            qs = qs.filter(read_at__isnull=True)
        return qs


class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=MarkReadSerializer, responses={200: None}, tags=["notifications"])
    def post(self, request):
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = services.mark_read(request.user, serializer.validated_data.get("ids"))
        return Response({"updated": count})


class UnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["notifications"])
    def get(self, request):
        return Response({"unread": Notification.objects.filter(user=request.user, read_at__isnull=True).count()})
