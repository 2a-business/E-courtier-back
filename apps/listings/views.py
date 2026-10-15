from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminRole, IsListingManager

from . import selectors, services
from .models import Amenity, Listing, ListingPhoto
from .serializers import (
    AmenitySerializer,
    FeaturedSerializer,
    ListingDetailSerializer,
    ListingWriteSerializer,
    ModerationActionSerializer,
    OwnerListingSerializer,
    PhotoReorderSerializer,
    PhotoSerializer,
    PhotoUploadSerializer,
    PublicationSerializer,
)


def detail_response(request, listing, status_code=status.HTTP_200_OK, refetch=True):
    if refetch:
        listing = selectors.visible_listing_for(request.user, listing.pk)
    from apps.visits.selectors import user_can_see_exact_address

    context = {"request": request, "can_see_address": user_can_see_exact_address(request.user, listing)}
    return Response(ListingDetailSerializer(listing, context=context).data, status=status_code)


@extend_schema(tags=["listings"])
class AmenityListView(generics.ListAPIView):
    queryset = Amenity.objects.all()
    serializer_class = AmenitySerializer
    permission_classes = [AllowAny]
    pagination_class = None


class ListingCreateView(APIView):
    permission_classes = [IsListingManager]

    @extend_schema(request=ListingWriteSerializer, responses={201: ListingDetailSerializer}, tags=["listings"])
    def post(self, request):
        serializer = ListingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        listing = services.create_listing(owner=request.user, **serializer.validated_data)
        return detail_response(request, listing, status.HTTP_201_CREATED)


class ListingDetailView(APIView):
    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    @extend_schema(responses={200: ListingDetailSerializer}, tags=["listings"])
    def get(self, request, pk):
        try:
            listing = selectors.visible_listing_for(request.user, pk)
        except Listing.DoesNotExist:
            return Response({"code": "not_found", "detail": "Annonce introuvable."}, status=404)
        return detail_response(request, listing, refetch=False)

    @extend_schema(request=ListingWriteSerializer, responses={200: ListingDetailSerializer}, tags=["listings"])
    def patch(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        services.ensure_can_manage(request.user, listing)
        serializer = ListingWriteSerializer(listing, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        listing = services.update_listing(actor=request.user, listing=listing, **serializer.validated_data)
        return detail_response(request, listing)

    @extend_schema(responses={204: None}, tags=["listings"])
    def delete(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        services.delete_listing(actor=request.user, listing=listing)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ListingPublicationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PublicationSerializer, responses={200: ListingDetailSerializer}, tags=["listings"])
    def post(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        serializer = PublicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        listing = services.change_publication(actor=request.user, listing=listing, target=serializer.validated_data["status"])
        return detail_response(request, listing)


class ListingPhotoListView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_scope = "uploads"

    @extend_schema(request=PhotoUploadSerializer, responses={201: PhotoSerializer}, tags=["listings"])
    def post(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        services.ensure_can_manage(request.user, listing)
        serializer = PhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        photo = services.add_photo(
            actor=request.user, listing=listing, uploaded=serializer.validated_data["image"],
            caption=serializer.validated_data.get("caption", ""),
        )
        return Response(PhotoSerializer(photo, context={"request": request}).data, status=status.HTTP_201_CREATED)


class ListingPhotoReorderView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PhotoReorderSerializer, responses={204: None}, tags=["listings"])
    def post(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        serializer = PhotoReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reorder_photos(actor=request.user, listing=listing, ordered_ids=serializer.validated_data["ids"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ListingPhotoDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["listings"])
    def delete(self, request, pk, photo_id):
        photo = get_object_or_404(ListingPhoto.objects.select_related("listing"), pk=photo_id, listing_id=pk)
        services.delete_photo(actor=request.user, photo=photo)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ListingPhotoPrimaryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: PhotoSerializer}, tags=["listings"])
    def post(self, request, pk, photo_id):
        photo = get_object_or_404(ListingPhoto.objects.select_related("listing"), pk=photo_id, listing_id=pk)
        photo = services.set_primary_photo(actor=request.user, photo=photo)
        return Response(PhotoSerializer(photo, context={"request": request}).data)


@extend_schema(tags=["dashboard"])
class MyListingsView(generics.ListAPIView):
    serializer_class = OwnerListingSerializer
    permission_classes = [IsListingManager]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Listing.objects.none()
        qs = selectors.owner_listings(self.request.user)
        status_filter = self.request.query_params.get("publication_status")
        return qs.filter(publication_status=status_filter) if status_filter else qs


class MyStatsView(APIView):
    permission_classes = [IsListingManager]

    @extend_schema(responses={200: None}, tags=["dashboard"])
    def get(self, request):
        from apps.dashboard import owner_stats

        return Response(owner_stats(request.user))


# --- Administration -----------------------------------------------------------


@extend_schema(tags=["admin"])
class AdminListingListView(generics.ListAPIView):
    serializer_class = OwnerListingSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = ["publication_status", "verification_status", "is_featured"]

    def get_queryset(self):
        qs = (
            Listing.objects.select_related("owner")
            .prefetch_related(selectors.primary_photo_prefetch())
            .annotate(
                visits_pending=Count("visits", filter=Q(visits__status="PENDING"), distinct=True),
                reports_open=Count("reports", filter=Q(reports__status__in=["OPEN", "IN_REVIEW"]), distinct=True),
            )
            .order_by("-created_at")
        )
        q = self.request.query_params.get("q")
        return qs.filter(Q(title__icontains=q) | Q(district__icontains=q)) if q else qs


class AdminListingModerationView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(request=ModerationActionSerializer, responses={200: ListingDetailSerializer}, tags=["admin"])
    def post(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        serializer = ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        listing = services.moderate_listing(actor=request.user, listing=listing, **serializer.validated_data)
        return detail_response(request, listing)


class AdminListingFeaturedView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(request=FeaturedSerializer, responses={200: ListingDetailSerializer}, tags=["admin"])
    def post(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        serializer = FeaturedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        listing = services.set_featured(actor=request.user, listing=listing, featured=serializer.validated_data["featured"])
        return detail_response(request, listing)
