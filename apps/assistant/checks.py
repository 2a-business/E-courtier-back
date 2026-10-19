"""Contrôles de configuration de l'assistant IA (``manage.py check``).

Un fournisseur inconnu est une erreur (faute de frappe) ; un fournisseur choisi sans clé ou sans modèle
est signalé, car l'assistant fonctionnerait alors silencieusement en mode règles.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register

from .providers import SUPPORTED_PROVIDERS


@register()
def check_llm_configuration(app_configs=None, **kwargs):
    name = (settings.LLM_PROVIDER or "rules").lower()
    if name not in SUPPORTED_PROVIDERS:
        return [Error(
            f"LLM_PROVIDER={settings.LLM_PROVIDER!r} est inconnu.",
            hint=f"Valeurs acceptées : {', '.join(SUPPORTED_PROVIDERS)}.",
            id="assistant.E001",
        )]
    if name == "rules":
        return []
    missing = [var for var, value in (("LLM_API_KEY", settings.LLM_API_KEY), ("LLM_MODEL", settings.LLM_MODEL)) if not value]
    if missing:
        return [Warning(
            f"LLM_PROVIDER={name} mais {' et '.join(missing)} absent(s) : l'assistant fonctionne en mode règles.",
            hint="Renseignez la clé (côté serveur uniquement) et le modèle, ou remettez LLM_PROVIDER=rules.",
            id="assistant.W001",
        )]
    return []
