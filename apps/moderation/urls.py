from django.urls import path

from . import views

urlpatterns = [
    path("", views.ReportCreateView.as_view(), name="reports"),
    path("mine/", views.MyReportsView.as_view(), name="reports-mine"),
]

admin_urlpatterns = [
    path("dashboard/", views.AdminDashboardView.as_view(), name="admin-dashboard"),
    path("reports/", views.AdminReportListView.as_view(), name="admin-reports"),
    path("reports/<int:pk>/", views.AdminReportHandleView.as_view(), name="admin-report-handle"),
    path("audit-log/", views.AuditLogListView.as_view(), name="admin-audit-log"),
]
