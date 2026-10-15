from django.urls import path

from . import views

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="auth-register"),
    path("login/", views.LoginView.as_view(), name="auth-login"),
    path("refresh/", views.RefreshView.as_view(), name="auth-refresh"),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("me/", views.MeView.as_view(), name="auth-me"),
    path("password-reset/", views.PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path("password-reset/confirm/", views.PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),
]

admin_urlpatterns = [
    path("users/", views.AdminUserListView.as_view(), name="admin-users"),
    path("users/<int:pk>/role/", views.AdminUserRoleView.as_view(), name="admin-user-role"),
    path("users/<int:pk>/active/", views.AdminUserActiveView.as_view(), name="admin-user-active"),
]
