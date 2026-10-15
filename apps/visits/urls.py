from django.urls import path

from . import views

urlpatterns = [
    path("", views.VisitListCreateView.as_view(), name="visits"),
    path("slots/", views.AvailableSlotsView.as_view(), name="visit-slots"),
    path("manage/slots/", views.HostSlotsView.as_view(), name="visit-host-slots"),
    path("manage/slots/<int:pk>/", views.HostSlotDetailView.as_view(), name="visit-host-slot"),
    path("<int:pk>/", views.VisitDetailView.as_view(), name="visit-detail"),
    path("<int:pk>/status/", views.VisitStatusView.as_view(), name="visit-status"),
]
