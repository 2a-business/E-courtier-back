from django.urls import path

from . import views

urlpatterns = [
    path("", views.TransactionListCreateView.as_view(), name="transactions"),
    path("config/", views.PaymentConfigView.as_view(), name="transactions-config"),
    path("quote/", views.QuoteView.as_view(), name="transactions-quote"),
    path("<uuid:pk>/", views.TransactionDetailView.as_view(), name="transaction-detail"),
    path("<uuid:pk>/wave/", views.StartWaveView.as_view(), name="transaction-wave"),
    path("<uuid:pk>/declare/", views.DeclarePaymentView.as_view(), name="transaction-declare"),
    path("<uuid:pk>/simulate/", views.SimulatePaymentView.as_view(), name="transaction-simulate"),
    path("<uuid:pk>/cancel/", views.CancelTransactionView.as_view(), name="transaction-cancel"),
]

admin_urlpatterns = [
    path("transactions/", views.AdminTransactionListView.as_view(), name="admin-transactions"),
    path("transactions/<uuid:pk>/confirm/", views.AdminConfirmView.as_view(), name="admin-transaction-confirm"),
    path("transactions/<uuid:pk>/status/", views.AdminStatusView.as_view(), name="admin-transaction-status"),
]
