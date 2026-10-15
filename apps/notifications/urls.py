from django.urls import path

from . import views

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="notifications"),
    path("read/", views.NotificationMarkReadView.as_view(), name="notifications-read"),
    path("unread-count/", views.UnreadCountView.as_view(), name="notifications-unread"),
]
