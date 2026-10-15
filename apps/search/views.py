from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.listings.serializers import ListingCardSerializer

from .selectors import locations, search_listings
from .serializers import SearchParamsSerializer


@extend_schema(parameters=[SearchParamsSerializer], tags=["search"])
class ListingSearchView(generics.ListAPIView):
    """Recherche publique paginée parmi les annonces publiées."""

    serializer_class = ListingCardSerializer
    permission_classes = [AllowAny]
    filter_backends = []

    def get_queryset(self):
        params = SearchParamsSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        return search_listings(params.validated_data)


class LocationsView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses={200: None}, tags=["search"])
    def get(self, request):
        return Response(locations())
