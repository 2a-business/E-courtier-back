"""Format d'erreur homogène pour l'API.

Toutes les erreurs ont la forme ``{"code": str, "detail": str, "errors": {...}?}``.
"""

import logging

from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.core_errors import BusinessError

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    if isinstance(exc, BusinessError):
        return Response({"code": exc.code, "detail": exc.message}, status=exc.http_status)
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(detail=exc.message_dict if hasattr(exc, "error_dict") else exc.messages)
    elif isinstance(exc, Http404):
        exc = exceptions.NotFound("Ressource introuvable.")
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        logger.exception("Erreur non gérée", exc_info=exc)
        return Response(
            {"code": "server_error", "detail": "Une erreur interne est survenue. Réessayez plus tard."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, exceptions.ValidationError):
        response.data = {"code": "validation_error", "detail": "Certaines données sont invalides.", "errors": response.data}
    else:
        detail = response.data.get("detail", "") if isinstance(response.data, dict) else response.data
        code = getattr(exc, "default_code", "error")
        if isinstance(exc, exceptions.Throttled):
            detail = "Trop de requêtes. Merci de patienter avant de réessayer."
            code = "throttled"
        response.data = {"code": code, "detail": str(detail)}
    return response
