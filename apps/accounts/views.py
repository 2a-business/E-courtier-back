from django.conf import settings
from django.contrib.auth import authenticate
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from . import services
from .models import User
from .permissions import IsAdminRole
from .serializers import (
    AdminActiveSerializer,
    AdminRoleSerializer,
    AdminUserSerializer,
    AuthResponseSerializer,
    LoginSerializer,
    MeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
)

CSRF_HEADER = "HTTP_X_REQUESTED_WITH"


def _set_refresh_cookie(response, refresh: RefreshToken):
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        str(refresh),
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        path=settings.REFRESH_COOKIE_PATH,
    )


def _auth_response(user, status_code=status.HTTP_200_OK):
    refresh = RefreshToken.for_user(user)
    response = Response({"access": str(refresh.access_token), "user": MeSerializer(user).data}, status=status_code)
    _set_refresh_cookie(response, refresh)
    return response


def _unauthorized(detail):
    # Vues sans authentificateur : DRF convertirait AuthenticationFailed en 403, on renvoie un vrai 401.
    return Response({"code": "not_authenticated", "detail": detail}, status=status.HTTP_401_UNAUTHORIZED)


def _require_ajax_header(request):
    # Le cookie de rafraîchissement est envoyé automatiquement : on exige un en-tête personnalisé,
    # qu'un site tiers ne peut pas ajouter sans pré-vol CORS (bloqué par CORS_ALLOWED_ORIGINS).
    if request.META.get(CSRF_HEADER) != "XMLHttpRequest":
        raise PermissionDenied("En-tête X-Requested-With manquant.")


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "register"

    @extend_schema(request=RegisterSerializer, responses={201: AuthResponseSerializer}, tags=["auth"])
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.register_user(**serializer.validated_data)
        return _auth_response(user, status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "auth"

    @extend_schema(request=LoginSerializer, responses={200: AuthResponseSerializer}, tags=["auth"])
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request, email=serializer.validated_data["email"].lower(), password=serializer.validated_data["password"]
        )
        if user is None:
            return _unauthorized("Adresse e-mail ou mot de passe incorrect.")
        return _auth_response(user)


class RefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "refresh"

    @extend_schema(request=None, responses={200: AuthResponseSerializer}, tags=["auth"])
    def post(self, request):
        _require_ajax_header(request)
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not raw:
            return _unauthorized("Session expirée.")
        try:
            old = RefreshToken(raw)
            user = User.objects.get(pk=old["user_id"], is_active=True)
            old.blacklist()
        except (TokenError, User.DoesNotExist, KeyError):
            response = Response({"code": "not_authenticated", "detail": "Session expirée."}, status=401)
            response.delete_cookie(settings.REFRESH_COOKIE_NAME, path=settings.REFRESH_COOKIE_PATH)
            return response
        return _auth_response(user)


class LogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(request=None, responses={204: None}, tags=["auth"])
    def post(self, request):
        _require_ajax_header(request)
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                pass
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(settings.REFRESH_COOKIE_NAME, path=settings.REFRESH_COOKIE_PATH)
        return response


@extend_schema(tags=["auth"])
class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = MeSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]

    def get_object(self):
        return User.objects.select_related("profile").get(pk=self.request.user.pk)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "password_reset"

    @extend_schema(request=PasswordResetRequestSerializer, responses={202: None}, tags=["auth"])
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(serializer.validated_data["email"])
        return Response(
            {"detail": "Si un compte correspond à cette adresse, un lien de réinitialisation a été envoyé."},
            status=status.HTTP_202_ACCEPTED,
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "password_reset"

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: None}, tags=["auth"])
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.confirm_password_reset(**serializer.validated_data)
        return Response({"detail": "Mot de passe mis à jour. Vous pouvez vous connecter."})


# --- Administration des comptes ----------------------------------------------------


@extend_schema(tags=["admin"])
class AdminUserListView(generics.ListAPIView):
    serializer_class = AdminUserSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = ["role", "is_active"]

    def get_queryset(self):
        qs = User.objects.order_by("-date_joined")
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(email__icontains=q) | qs.filter(last_name__icontains=q)
        return qs


class AdminUserRoleView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(request=AdminRoleSerializer, responses={200: AdminUserSerializer}, tags=["admin"])
    def post(self, request, pk):
        serializer = AdminRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = generics.get_object_or_404(User, pk=pk)
        user = services.change_role(actor=request.user, target=target, new_role=serializer.validated_data["role"])
        return Response(AdminUserSerializer(user).data)


class AdminUserActiveView(APIView):
    permission_classes = [IsAdminRole]

    @extend_schema(request=AdminActiveSerializer, responses={200: AdminUserSerializer}, tags=["admin"])
    def post(self, request, pk):
        serializer = AdminActiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = generics.get_object_or_404(User, pk=pk)
        user = services.set_active(actor=request.user, target=target, **serializer.validated_data)
        return Response(AdminUserSerializer(user).data)
