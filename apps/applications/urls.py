from django.urls import path

from . import views

urlpatterns = [
    path("", views.ApplicationListCreateView.as_view(), name="applications"),
    path("received/", views.ReceivedApplicationListView.as_view(), name="applications-received"),
    path("<uuid:pk>/", views.ApplicationDetailView.as_view(), name="application-detail"),
    path("<uuid:pk>/documents/", views.ApplicationDocumentsView.as_view(), name="application-documents"),
    path("<uuid:pk>/submit/", views.SubmitView.as_view(), name="application-submit"),
    path("<uuid:pk>/review/", views.StartReviewView.as_view(), name="application-review"),
    path("<uuid:pk>/request-info/", views.RequestInfoView.as_view(), name="application-request-info"),
    path("<uuid:pk>/decision/", views.DecisionView.as_view(), name="application-decision"),
    path("<uuid:pk>/notes/", views.NotesView.as_view(), name="application-notes"),
    path("documents/<int:doc_id>/", views.ApplicationDocumentView.as_view(), name="application-document"),
    path("documents/<int:doc_id>/file/", views.ApplicationDocumentFileView.as_view(), name="application-document-file"),
]
