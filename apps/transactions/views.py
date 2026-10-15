from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminRole
from apps.listings.models import Listing, PublicationStatus

from . import services
from .models import Transaction
from .serializers import (
    AdminConfirmSerializer,
    AdminStatusSerializer,
    AttemptSerializer,
    TransactionCancelSerializer,
    CreateTransactionSerializer,
    DeclareSerializer,
    TransactionDetailSerializer,
    TransactionSerializer,
)


def _base_qs():
    return Transaction.objects.select_related("listing", "customer", "owner", "contract").prefetch_related("listing__photos")


def _get_visible(request, pk):
    tx = get_object_or_404(_base_qs().prefetch_related("events", "attempts"), pk=pk)
    if not services.visible_to(request.user, tx):
        raise PermissionDenied("Ce dossier ne vous concerne pas.")
    return tx


def _detail(request, tx, code=status.HTTP_200_OK):
    tx = _get_visible(request, tx.pk)
    return Response(TransactionDetailSerializer(tx, context={"request": request}).data, status=code)


class PaymentConfigView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["transactions"])
    def get(self, request):
        return Response({
            "wave_configured": bool(settings.WAVE_PAYMENT_LINK),
            "simulation_enabled": settings.PAYMENT_SIMULATION_ENABLED,
            "dossier_fee": settings.DOSSIER_FEE_XOF,
            "currency": "XOF",
            "escrow_supported": False,
        })


class QuoteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[OpenApiParameter("listing", str, required=True)], responses={200: None}, tags=["transactions"])
    def get(self, request):
        listing = get_object_or_404(Listing, pk=request.query_params.get("listing"), publication_status=PublicationStatus.PUBLISHED)
        return Response(services.quote(listing))


class TransactionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[OpenApiParameter("role", str, enum=["customer", "owner"])], responses={200: TransactionSerializer(many=True)}, tags=["transactions"])
    def get(self, request):
        qs = _base_qs()
        qs = qs.filter(owner=request.user) if request.query_params.get("role") == "owner" else qs.filter(customer=request.user)
        return Response(TransactionSerializer(qs[:100], many=True, context={"request": request}).data)

    @extend_schema(
        request=CreateTransactionSerializer,
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER)],
        responses={201: TransactionDetailSerializer, 200: TransactionDetailSerializer},
        tags=["transactions"],
    )
    def post(self, request):
        serializer = CreateTransactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tx, created = services.create_transaction(
            customer=request.user, listing_id=serializer.validated_data["listing"],
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return _detail(request, tx, status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class TransactionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: TransactionDetailSerializer}, tags=["transactions"])
    def get(self, request, pk):
        return Response(TransactionDetailSerializer(_get_visible(request, pk), context={"request": request}).data)


class StartWaveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: None}, tags=["transactions"])
    def post(self, request, pk):
        tx = _get_visible(request, pk)
        attempt, checkout = services.start_wave_payment(customer=request.user, tx=tx)
        return Response({"attempt": AttemptSerializer(attempt).data, "checkout": checkout})


class DeclarePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=DeclareSerializer, responses={200: TransactionDetailSerializer}, tags=["transactions"])
    def post(self, request, pk):
        tx = _get_visible(request, pk)
        serializer = DeclareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.declare_payment(customer=request.user, tx=tx, **serializer.validated_data)
        return _detail(request, tx)


class SimulatePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: TransactionDetailSerializer}, tags=["transactions"])
    def post(self, request, pk):
        tx = _get_visible(request, pk)
        services.simulate_payment(actor=request.user, tx=tx)
        return _detail(request, tx)


class CancelTransactionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=TransactionCancelSerializer, responses={200: TransactionDetailSerializer}, tags=["transactions"])
    def post(self, request, pk):
        tx = _get_visible(request, pk)
        serializer = TransactionCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.change_status(actor=request.user, tx=tx, target="CANCELLED", note=serializer.validated_data["note"])
        return _detail(request, tx)


@extend_schema(tags=["admin"])
class AdminTransactionListView(generics.ListAPIView):
    serializer_class = TransactionDetailSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = ["status", "is_simulated"]

    def get_queryset(self):
        return _base_qs().prefetch_related("events", "attempts")


class AdminConfirmView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(request=AdminConfirmSerializer, responses={200: TransactionDetailSerializer}, tags=["admin"])
    def post(self, request, pk):
        tx = get_object_or_404(Transaction, pk=pk)
        serializer = AdminConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.confirm_payment(actor=request.user, tx=tx, **serializer.validated_data)
        return _detail(request, tx)


class AdminStatusView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(request=AdminStatusSerializer, responses={200: TransactionDetailSerializer}, tags=["admin"])
    def post(self, request, pk):
        tx = get_object_or_404(Transaction, pk=pk)
        serializer = AdminStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.change_status(actor=request.user, tx=tx, target=serializer.validated_data["status"], note=serializer.validated_data["note"])
        return _detail(request, tx)
