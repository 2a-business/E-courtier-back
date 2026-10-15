from django.urls import path

from . import views

urlpatterns = [
    path("", views.ContractListView.as_view(), name="contracts"),
    path("<uuid:pk>/", views.ContractDetailView.as_view(), name="contract-detail"),
    path("<uuid:pk>/download/", views.ContractDownloadView.as_view(), name="contract-download"),
    path("<uuid:pk>/terms/", views.ContractTermsView.as_view(), name="contract-terms"),
    path("<uuid:pk>/send/", views.ContractSendView.as_view(), name="contract-send"),
    path("<uuid:pk>/sign/", views.ContractSignView.as_view(), name="contract-sign"),
    path("<uuid:pk>/cancel/", views.ContractCancelView.as_view(), name="contract-cancel"),
]
