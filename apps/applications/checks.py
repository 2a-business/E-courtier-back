"""Contrôle de la configuration des pièces obligatoires du dossier locatif (``manage.py check``)."""

from django.conf import settings
from django.core.checks import Error, register

from .models import ApplicationDocumentType


@register()
def check_required_documents(app_configs=None, **kwargs):
    unknown = sorted(set().union(*settings.RENTAL_APPLICATION_REQUIRED_DOCS) - set(ApplicationDocumentType.values))
    if unknown:
        return [Error(
            f"RENTAL_APPLICATION_REQUIRED_DOCS contient des types inconnus : {', '.join(unknown)}.",
            hint=f"Types acceptés : {', '.join(ApplicationDocumentType.values)} (groupes séparés par « , », alternatives par « | »).",
            id="applications.E001",
        )]
    return []
