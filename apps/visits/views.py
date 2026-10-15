from datetime import datetime, time

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.listings.models import Listing, PublicationStatus
from apps.listings.services import ensure_can_manage

from . import selectors, services
from .models import Visit, VisitSlot
from .serializers import (
    BookSerializer,
    HostSlotSerializer,
    SlotBatchSerializer,
    SlotSerializer,
    VisitSerializer,
    VisitStatusSerializer,
)


class AvailableSlotsView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("listing", str, required=True), OpenApiParameter("from", str), OpenApiParameter("to", str)],
        responses={200: SlotSerializer(many=True)},
        tags=["visits"],
    )
    def get(self, request):
        listing = get_object_or_404(Listing, pk=request.query_params.get("listing"), publication_status=PublicationStatus.PUBLISHED)
        tz = timezone.get_current_timezone()

        def parse(key, default_time):
            raw = request.query_params.get(key)
            if not raw:
                return None
            try:
                return timezone.make_aware(datetime.combine(datetime.fromisoformat(raw).date(), default_time), tz)
            except ValueError:
                return None

        start = max(filter(None, [parse("from", time.min), timezone.now() + services.MIN_NOTICE]))
        end = parse("to", time.max)
        slots = selectors.available_slots(listing, start=start, end=end)[:200]
        return Response(SlotSerializer(slots, many=True).data)


class VisitListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("role", str, enum=["customer", "host"]), OpenApiParameter("status", str)],
        responses={200: VisitSerializer(many=True)},
        tags=["visits"],
    )
    def get(self, request):
        role = request.query_params.get("role", "customer")
        qs = selectors.visits_for(request.user, role)
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        if request.query_params.get("listing"):
            qs = qs.filter(listing_id=request.query_params["listing"])
        qs = qs.order_by("slot__starts_at")[:200]
        return Response(VisitSerializer(qs, many=True, context={"request": request}).data)

    @extend_schema(request=BookSerializer, responses={201: VisitSerializer}, tags=["visits"])
    def post(self, request):
        serializer = BookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        visit = services.book_visit(customer=request.user, **serializer.validated_data)
        visit = selectors.visits_for(request.user, "customer").get(pk=visit.pk)
        return Response(VisitSerializer(visit, context={"request": request}).data, status=status.HTTP_201_CREATED)


class VisitDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        visit = get_object_or_404(Visit.objects.select_related("listing", "slot", "customer", "host"), pk=pk)
        if request.user.pk not in (visit.customer_id, visit.host_id) and not request.user.is_admin:
            raise PermissionDenied("Cette visite ne vous concerne pas.")
        return visit

    @extend_schema(responses={200: VisitSerializer}, tags=["visits"])
    def get(self, request, pk):
        return Response(VisitSerializer(self._get(request, pk), context={"request": request}).data)


class VisitStatusView(VisitDetailView):
    @extend_schema(request=VisitStatusSerializer, responses={200: VisitSerializer}, tags=["visits"])
    def post(self, request, pk):
        visit = self._get(request, pk)
        serializer = VisitStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        visit = services.change_status(
            actor=request.user, visit=visit, target=serializer.validated_data["status"],
            reason=serializer.validated_data["reason"],
        )
        return Response(VisitSerializer(visit, context={"request": request}).data)


class HostSlotsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[OpenApiParameter("listing", str, required=True)], responses={200: HostSlotSerializer(many=True)}, tags=["visits"])
    def get(self, request):
        listing = get_object_or_404(Listing, pk=request.query_params.get("listing"))
        ensure_can_manage(request.user, listing)
        qs = VisitSlot.objects.filter(listing=listing, starts_at__gte=timezone.now()).prefetch_related("visits")
        return Response(HostSlotSerializer(qs[:300], many=True).data)

    @extend_schema(request=SlotBatchSerializer, responses={201: HostSlotSerializer(many=True)}, tags=["visits"])
    def post(self, request):
        serializer = SlotBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        listing = get_object_or_404(Listing, pk=data.pop("listing"))
        slots = services.create_slots(actor=request.user, listing=listing, **data)
        return Response(HostSlotSerializer(slots, many=True).data, status=status.HTTP_201_CREATED)


class HostSlotDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["visits"])
    def delete(self, request, pk):
        slot = get_object_or_404(VisitSlot.objects.select_related("listing"), pk=pk)
        services.remove_slot(actor=request.user, slot=slot)
        return Response(status=status.HTTP_204_NO_CONTENT)
