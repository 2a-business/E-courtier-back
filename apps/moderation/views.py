from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminRole
from apps.listings.models import Listing, PublicationStatus

from . import services
from .models import AuditLog, Report
from .serializers import AdminReportSerializer, AuditLogSerializer, ReportCreateSerializer, ReportHandleSerializer, ReportSerializer


class ReportCreateView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "reports"

    @extend_schema(request=ReportCreateSerializer, responses={201: ReportSerializer}, tags=["reports"])
    def post(self, request):
        s = ReportCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        listing = get_object_or_404(Listing, pk=s.validated_data["listing"], publication_status=PublicationStatus.PUBLISHED)
        report = services.create_report(
            listing=listing, reporter=request.user, reason=s.validated_data["reason"], details=s.validated_data["details"]
        )
        return Response(ReportSerializer(report).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["reports"])
class MyReportsView(generics.ListAPIView):
    serializer_class = ReportSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Report.objects.none()
        return Report.objects.filter(reporter=self.request.user).select_related("listing")


@extend_schema(tags=["admin"])
class AdminReportListView(generics.ListAPIView):
    serializer_class = AdminReportSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = ["status", "reason"]
    queryset = Report.objects.select_related("listing", "reporter")


class AdminReportHandleView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(request=ReportHandleSerializer, responses={200: AdminReportSerializer}, tags=["admin"])
    def post(self, request, pk):
        report = get_object_or_404(Report, pk=pk)
        s = ReportHandleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        report = services.handle_report(
            actor=request.user, report=report, new_status=s.validated_data["status"], note=s.validated_data["note"],
            suspend_listing=s.validated_data["suspend_listing"],
        )
        return Response(AdminReportSerializer(report).data)


@extend_schema(tags=["admin"])
class AuditLogListView(generics.ListAPIView):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = ["action", "target_type"]
    queryset = AuditLog.objects.select_related("actor")


class AdminDashboardView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request):
        from apps.dashboard import admin_stats

        return Response(admin_stats())
