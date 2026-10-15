from django.urls import path

from . import views

urlpatterns = [
    path("listings/<uuid:pk>/", views.ListingReviewsView.as_view(), name="listing-reviews"),
    path("received/", views.MyReceivedReviewsView.as_view(), name="reviews-received"),
]

admin_urlpatterns = [
    path("reviews/", views.AdminReviewListView.as_view(), name="admin-reviews"),
    path("reviews/<int:pk>/moderation/", views.AdminReviewModerationView.as_view(), name="admin-review-moderation"),
]
