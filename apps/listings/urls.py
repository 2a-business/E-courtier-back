from django.urls import path

from . import views

urlpatterns = [
    path("", views.ListingCreateView.as_view(), name="listing-create"),
    path("mine/", views.MyListingsView.as_view(), name="listing-mine"),
    path("mine/stats/", views.MyStatsView.as_view(), name="listing-mine-stats"),
    path("<uuid:pk>/", views.ListingDetailView.as_view(), name="listing-detail"),
    path("<uuid:pk>/publication/", views.ListingPublicationView.as_view(), name="listing-publication"),
    path("<uuid:pk>/photos/", views.ListingPhotoListView.as_view(), name="listing-photos"),
    path("<uuid:pk>/photos/reorder/", views.ListingPhotoReorderView.as_view(), name="listing-photos-reorder"),
    path("<uuid:pk>/photos/<int:photo_id>/", views.ListingPhotoDetailView.as_view(), name="listing-photo"),
    path("<uuid:pk>/photos/<int:photo_id>/primary/", views.ListingPhotoPrimaryView.as_view(), name="listing-photo-primary"),
]

admin_urlpatterns = [
    path("listings/", views.AdminListingListView.as_view(), name="admin-listings"),
    path("listings/<uuid:pk>/moderation/", views.AdminListingModerationView.as_view(), name="admin-listing-moderation"),
    path("listings/<uuid:pk>/featured/", views.AdminListingFeaturedView.as_view(), name="admin-listing-featured"),
]
