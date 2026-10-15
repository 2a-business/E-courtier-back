from django.urls import path

from . import views

urlpatterns = [
    path("listings/<uuid:pk>/documents/", views.ListingDocumentsView.as_view(), name="verification-documents"),
    path("listings/<uuid:pk>/submit/", views.ListingSubmitView.as_view(), name="verification-submit"),
    path("listings/<uuid:pk>/requests/", views.ListingRequestsView.as_view(), name="verification-requests"),
    path("documents/<int:doc_id>/", views.DocumentDetailView.as_view(), name="verification-document"),
    path("documents/<int:doc_id>/file/", views.DocumentFileView.as_view(), name="verification-document-file"),
]

admin_urlpatterns = [
    path("verifications/", views.AdminRequestListView.as_view(), name="admin-verifications"),
    path("verifications/stats/", views.AdminVerificationStatsView.as_view(), name="admin-verification-stats"),
    path("verifications/<int:pk>/", views.AdminRequestDetailView.as_view(), name="admin-verification"),
    path("verifications/<int:pk>/decision/", views.AdminDecisionView.as_view(), name="admin-verification-decision"),
]
