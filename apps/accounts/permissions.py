from rest_framework.permissions import BasePermission

from .models import Role


class IsAdminRole(BasePermission):
    """Rôle ADMIN vérifié en base, jamais d'après une donnée du client."""

    message = "Action réservée aux administrateurs."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == Role.ADMIN)


class IsListingManager(BasePermission):
    message = "Action réservée aux propriétaires et agents."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.can_manage_listings)
