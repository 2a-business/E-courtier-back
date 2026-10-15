from django.urls import path

from . import views

urlpatterns = [
    path("chat/", views.ChatView.as_view(), name="assistant-chat"),
    path("info/", views.AssistantInfoView.as_view(), name="assistant-info"),
    path("conversations/<uuid:pk>/", views.ConversationView.as_view(), name="assistant-conversation"),
]

admin_urlpatterns = [path("assistant/usage/", views.AssistantUsageView.as_view(), name="admin-assistant-usage")]
