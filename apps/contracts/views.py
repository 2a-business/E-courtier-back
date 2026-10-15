from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Contract
from .serializers import ContractCancelSerializer, ContractSerializer, SignSerializer, TermsSerializer


def _get(request, pk):
    contract = get_object_or_404(Contract.objects.select_related("transaction", "listing"), pk=pk)
    if not services.visible_to(request.user, contract):
        raise PermissionDenied("Ce contrat ne vous concerne pas.")
    return contract


def _out(request, contract):
    return Response(ContractSerializer(_get(request, contract.pk), context={"request": request}).data)


class ContractListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ContractSerializer(many=True)}, tags=["contracts"])
    def get(self, request):
        qs = Contract.objects.select_related("transaction", "listing").filter(
            Q(customer=request.user) | Q(owner=request.user)
        )
        return Response(ContractSerializer(qs[:100], many=True, context={"request": request}).data)


class ContractDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ContractSerializer}, tags=["contracts"])
    def get(self, request, pk):
        return _out(request, _get(request, pk))


class ContractDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={(200, "text/plain"): OpenApiTypes.STR}, tags=["contracts"])
    def get(self, request, pk):
        contract = _get(request, pk)
        version = contract.current_version
        response = HttpResponse(version.content + f"\n\nEmpreinte SHA-256 : {version.content_sha256}\n", content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="contrat-{contract.transaction.reference}-v{version.number}.txt"'
        response["Cache-Control"] = "no-store, private"
        return response


class ContractTermsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=TermsSerializer, responses={200: ContractSerializer}, tags=["contracts"])
    def post(self, request, pk):
        contract = _get(request, pk)
        s = TermsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.update_terms(actor=request.user, contract=contract, **s.validated_data)
        return _out(request, contract)


class ContractSendView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: ContractSerializer}, tags=["contracts"])
    def post(self, request, pk):
        contract = _get(request, pk)
        services.send_for_signature(actor=request.user, contract=contract)
        return _out(request, contract)


class ContractSignView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=SignSerializer, responses={200: ContractSerializer}, tags=["contracts"])
    def post(self, request, pk):
        contract = _get(request, pk)
        s = SignSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.sign(
            actor=request.user, contract=contract, ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""), **s.validated_data,
        )
        return _out(request, contract)


class ContractCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ContractCancelSerializer, responses={200: ContractSerializer}, tags=["contracts"])
    def post(self, request, pk):
        contract = _get(request, pk)
        s = ContractCancelSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.cancel(actor=request.user, contract=contract, **s.validated_data)
        return _out(request, contract)
