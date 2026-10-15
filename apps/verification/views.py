from django.db.models import Count
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminRole
from apps.listings.models import Listing, VerificationStatus
from apps.listings.selectors import primary_photo_prefetch
from apps.listings.services import ensure_can_manage
from apps.moderation.services import log_action

from . import services
from .models import DocumentType, RequestStatus, VerificationDocument, VerificationRequest
from .serializers import (
    AdminRequestSerializer,
    DecisionSerializer,
    DocumentSerializer,
    DocumentUploadSerializer,
    RequestSerializer,
)


class ListingDocumentsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_scope = "uploads"

    @extend_schema(responses={200: DocumentSerializer(many=True)}, tags=["verification"])
    def get(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        ensure_can_manage(request.user, listing)
        return Response(DocumentSerializer(listing.verification_documents.all(), many=True).data)

    @extend_schema(request=DocumentUploadSerializer, responses={201: DocumentSerializer}, tags=["verification"])
    def post(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        ensure_can_manage(request.user, listing)
        serializer = DocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc = services.upload_document(
            actor=request.user, listing=listing, doc_type=serializer.validated_data["doc_type"],
            uploaded=serializer.validated_data["file"],
        )
        return Response(DocumentSerializer(doc).data, status=status.HTTP_201_CREATED)


class DocumentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["verification"])
    def delete(self, request, doc_id):
        doc = get_object_or_404(VerificationDocument.objects.select_related("listing"), pk=doc_id)
        services.delete_document(actor=request.user, document=doc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DocumentFileView(APIView):
    """Sert le fichier après contrôle d'accès. Aucune mise en cache autorisée."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY}, tags=["verification"])
    def get(self, request, doc_id):
        doc = get_object_or_404(VerificationDocument.objects.select_related("listing"), pk=doc_id)
        if not services.can_read_document(request.user, doc):
            raise PermissionDenied("Accès refusé à ce justificatif.")
        if request.user.is_admin and doc.listing.owner_id != request.user.pk:
            log_action(actor=request.user, action="verification.document_viewed", target=doc)
        response = FileResponse(doc.file.open("rb"), content_type=doc.content_type)
        response["Content-Disposition"] = f'inline; filename="{doc.original_name}"'
        response["Cache-Control"] = "no-store, private"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
        return response


class ListingSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={201: RequestSerializer}, tags=["verification"])
    def post(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        req = services.submit(actor=request.user, listing=listing)
        return Response(RequestSerializer(req).data, status=status.HTTP_201_CREATED)


class ListingRequestsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: RequestSerializer(many=True)}, tags=["verification"])
    def get(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        ensure_can_manage(request.user, listing)
        qs = listing.verification_requests.select_related("decided_by").prefetch_related("documents")
        return Response(RequestSerializer(qs, many=True).data)


@extend_schema(tags=["admin"])
class AdminRequestListView(generics.ListAPIView):
    serializer_class = AdminRequestSerializer
    permission_classes = [IsAdminRole]

    def get_queryset(self):
        qs = VerificationRequest.objects.select_related("listing", "listing__owner", "submitted_by", "decided_by")
        qs = qs.prefetch_related("documents", "listing__photos")
        status_filter = self.request.query_params.get("status", RequestStatus.PENDING)
        if status_filter != "ALL":
            qs = qs.filter(status=status_filter)
        # File d'attente : les plus anciennes d'abord.
        return qs.order_by("submitted_at" if status_filter == RequestStatus.PENDING else "-submitted_at")


@extend_schema(tags=["admin"])
class AdminRequestDetailView(generics.RetrieveAPIView):
    serializer_class = AdminRequestSerializer
    permission_classes = [IsAdminRole]
    queryset = VerificationRequest.objects.select_related("listing", "submitted_by", "decided_by").prefetch_related("documents")


class AdminDecisionView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(request=DecisionSerializer, responses={200: AdminRequestSerializer}, tags=["admin"])
    def post(self, request, pk):
        req = get_object_or_404(VerificationRequest, pk=pk)
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        req = services.decide(actor=request.user, request=req, **serializer.validated_data)
        return Response(AdminRequestSerializer(req, context={"request": request}).data)


class AdminVerificationStatsView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request):
        by_status = dict(Listing.objects.values_list("verification_status").annotate(n=Count("id")))
        by_type = dict(VerificationDocument.objects.values_list("doc_type").annotate(n=Count("id")))
        recent = VerificationDocument.objects.select_related("listing").order_by("-uploaded_at")[:6]
        return Response({
            "listings_by_status": {s: by_status.get(s, 0) for s in VerificationStatus.values},
            "documents_by_type": [
                {"doc_type": t.value, "label": t.label, "count": by_type.get(t.value, 0)} for t in DocumentType
            ],
            "documents_total": sum(by_type.values()),
            "recent_uploads": [
                {"id": d.pk, "doc_type_label": d.get_doc_type_display(), "listing_title": d.listing.title,
                 "uploaded_at": d.uploaded_at}
                for d in recent
            ],
        })
