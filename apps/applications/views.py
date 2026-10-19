from django.db.models import Prefetch
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.listings.models import ListingPhoto

from . import services
from .models import ApplicationDocument, ApplicationStatus, RentalApplication
from .serializers import (
    ApplicationDetailSerializer,
    ApplicationDocumentSerializer,
    ApplicationInfoSerializer,
    ApplicationListSerializer,
    ApplicationNoteSerializer,
    ApplicationDecisionSerializer,
    ApplicationDocumentUploadSerializer,
    InfoRequestSerializer,
    NoteSerializer,
    OpenApplicationSerializer,
    SubmitSerializer,
)

TAGS = ["applications"]


def _base_qs():
    return RentalApplication.objects.select_related("listing", "listing__owner", "customer", "visit").prefetch_related(
        Prefetch("listing__photos", queryset=ListingPhoto.objects.order_by("-is_primary", "position", "id"))
    )


def _detail_qs():
    return _base_qs().prefetch_related("documents", "events__actor")


def _get_for(request, pk, *roles):
    app = get_object_or_404(_detail_qs(), pk=pk)
    services.ensure_role(request.user, app, *roles)
    return app


def _detail(request, app, code=status.HTTP_200_OK):
    app = get_object_or_404(_detail_qs(), pk=app.pk)
    return Response(ApplicationDetailSerializer(app, context={"request": request}).data, status=code)


class ApplicationListCreateView(APIView):
    """GET : dossiers du candidat connecté. POST : ouvrir (ou retrouver) le dossier lié à une visite confirmée."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ApplicationListSerializer(many=True)}, tags=TAGS)
    def get(self, request):
        qs = _base_qs().filter(customer=request.user)
        return Response(ApplicationListSerializer(qs, many=True, context={"request": request}).data)

    @extend_schema(request=OpenApplicationSerializer, responses={200: ApplicationDetailSerializer, 201: ApplicationDetailSerializer}, tags=TAGS)
    def post(self, request):
        serializer = OpenApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        app, created = services.open_for_visit(customer=request.user, visit_id=serializer.validated_data["visit"])
        return _detail(request, app, status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ReceivedApplicationListView(APIView):
    """Dossiers transmis pour les logements dont l'utilisateur est le propriétaire ou l'agent (jamais les brouillons)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("status", str, required=False)],
        responses={200: ApplicationListSerializer(many=True)}, tags=TAGS,
    )
    def get(self, request):
        qs = _base_qs().filter(listing__owner=request.user).exclude(status=ApplicationStatus.DRAFT).exclude(customer=request.user)
        wanted = request.query_params.get("status")
        if wanted in ApplicationStatus.values:
            qs = qs.filter(status=wanted)
        return Response(ApplicationListSerializer(qs.order_by("-submitted_at"), many=True, context={"request": request}).data)


class ApplicationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ApplicationDetailSerializer}, tags=TAGS)
    def get(self, request, pk):
        return _detail(request, _get_for(request, pk))

    @extend_schema(request=ApplicationInfoSerializer, responses={200: ApplicationDetailSerializer}, tags=TAGS)
    def patch(self, request, pk):
        app = _get_for(request, pk, "customer")
        serializer = ApplicationInfoSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_info(actor=request.user, app=app, **serializer.validated_data)
        return _detail(request, app)


class ApplicationDocumentsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_scope = "uploads"

    @extend_schema(request=ApplicationDocumentUploadSerializer, responses={201: ApplicationDocumentSerializer}, tags=TAGS)
    def post(self, request, pk):
        app = _get_for(request, pk, "customer")
        serializer = ApplicationDocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc = services.upload_document(
            actor=request.user, app=app, doc_type=serializer.validated_data["doc_type"],
            uploaded=serializer.validated_data["file"], replaces=serializer.validated_data.get("replaces"),
        )
        return Response(ApplicationDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)


class ApplicationDocumentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=TAGS)
    def delete(self, request, doc_id):
        doc = get_object_or_404(ApplicationDocument.objects.select_related("application__listing"), pk=doc_id)
        services.delete_document(actor=request.user, document=doc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ApplicationDocumentFileView(APIView):
    """Pièce privée transmise en flux après contrôle d'accès ; aucune mise en cache, aucune URL publique."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY}, tags=TAGS)
    def get(self, request, doc_id):
        doc = get_object_or_404(ApplicationDocument.objects.select_related("application__listing"), pk=doc_id)
        role = services.ensure_role(request.user, doc.application)
        services.record_document_view(actor=request.user, document=doc, role=role)
        response = FileResponse(doc.file.open("rb"), content_type=doc.content_type)
        response["Content-Disposition"] = f'inline; filename="{doc.original_name}"'
        response["Cache-Control"] = "no-store, private"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
        return response


class SubmitView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=SubmitSerializer, responses={200: ApplicationDetailSerializer}, tags=TAGS)
    def post(self, request, pk):
        app = _get_for(request, pk, "customer")
        serializer = SubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.submit(actor=request.user, app=app, consent=serializer.validated_data["consent"])
        return _detail(request, app)


class StartReviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: ApplicationDetailSerializer}, tags=TAGS)
    def post(self, request, pk):
        app = _get_for(request, pk, "responsible")
        services.start_review(actor=request.user, app=app)
        return _detail(request, app)


class RequestInfoView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=InfoRequestSerializer, responses={200: ApplicationDetailSerializer}, tags=TAGS)
    def post(self, request, pk):
        app = _get_for(request, pk, "responsible")
        serializer = InfoRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_info(actor=request.user, app=app, message=serializer.validated_data["message"])
        return _detail(request, app)


class DecisionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ApplicationDecisionSerializer, responses={200: ApplicationDetailSerializer}, tags=TAGS)
    def post(self, request, pk):
        app = _get_for(request, pk, "responsible")
        serializer = ApplicationDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.decide(actor=request.user, app=app, **serializer.validated_data)
        return _detail(request, app)


class NotesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=NoteSerializer, responses={201: ApplicationNoteSerializer}, tags=TAGS)
    def post(self, request, pk):
        app = _get_for(request, pk, "responsible")
        serializer = NoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = services.add_note(actor=request.user, app=app, text=serializer.validated_data["text"])
        return Response(ApplicationNoteSerializer(note).data, status=status.HTTP_201_CREATED)

