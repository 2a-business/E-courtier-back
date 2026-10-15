from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminRole
from apps.listings.models import Listing, PublicationStatus

from . import services
from .models import Review, ReviewStatus
from .serializers import AdminReviewSerializer, ReviewCreateSerializer, ReviewModerationSerializer, ReviewSerializer


class ListingReviewsView(APIView):
    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    @extend_schema(responses={200: None}, tags=["reviews"])
    def get(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk, publication_status=PublicationStatus.PUBLISHED)
        qs = Review.objects.filter(listing=listing, status=ReviewStatus.PUBLISHED).select_related("author")
        owner_stats = Review.objects.filter(listing__owner_id=listing.owner_id, status=ReviewStatus.PUBLISHED).aggregate(
            avg=Avg("owner_rating"), n=Count("id")
        )
        return Response({
            "results": ReviewSerializer(qs[:50], many=True).data,
            "can_review": services.can_review(request.user, listing),
            "owner_rating": {"average": round(owner_stats["avg"], 1) if owner_stats["avg"] else None, "count": owner_stats["n"]},
        })

    @extend_schema(request=ReviewCreateSerializer, responses={201: ReviewSerializer}, tags=["reviews"])
    def post(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        s = ReviewCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        review = services.create_review(author=request.user, listing=listing, **s.validated_data)
        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["dashboard"])
class MyReceivedReviewsView(generics.ListAPIView):
    serializer_class = AdminReviewSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Review.objects.none()
        return Review.objects.filter(listing__owner=self.request.user, status=ReviewStatus.PUBLISHED).select_related("author", "listing")


@extend_schema(tags=["admin"])
class AdminReviewListView(generics.ListAPIView):
    serializer_class = AdminReviewSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = ["status"]
    queryset = Review.objects.select_related("author", "listing")


class AdminReviewModerationView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(request=ReviewModerationSerializer, responses={200: AdminReviewSerializer}, tags=["admin"])
    def post(self, request, pk):
        review = get_object_or_404(Review, pk=pk)
        s = ReviewModerationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        review = services.moderate_review(actor=request.user, review=review, **s.validated_data)
        return Response(AdminReviewSerializer(review).data)
