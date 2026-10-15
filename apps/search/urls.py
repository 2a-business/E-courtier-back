from django.urls import path

from . import views

urlpatterns = [
    path("listings/", views.ListingSearchView.as_view(), name="search-listings"),
    path("locations/", views.LocationsView.as_view(), name="search-locations"),
]
