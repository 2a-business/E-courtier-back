"""Sélection du module de paramètres Django à partir de DJANGO_ENV.

Utilisé par manage.py (défaut : développement) et wsgi.py (défaut : production).
- DJANGO_ENV accepte uniquement « development », « test » ou « production » : une faute de frappe
  (« prod », « Production ») est refusée au lieu de retomber silencieusement sur le développement.
- DJANGO_ENV est lu dans l'environnement, puis dans backend/.env.
- Un DJANGO_SETTINGS_MODULE explicite est respecté, sauf s'il contredit DJANGO_ENV=production.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import dotenv_values

SETTINGS_BY_ENV = {
    "development": "config.settings.dev",
    "test": "config.settings.test",
    "production": "config.settings.prod",
}
ENV_FILE = Path(os.environ.get("DJANGO_DOTENV_FILE", Path(__file__).resolve().parent.parent / ".env"))


def resolve_environment(default: str) -> str:
    raw = os.environ.get("DJANGO_ENV") or (dotenv_values(ENV_FILE).get("DJANGO_ENV") if ENV_FILE.exists() else None) or default
    value = raw.strip().lower()
    if value not in SETTINGS_BY_ENV:
        raise ImproperlyConfigured(
            f"DJANGO_ENV={raw!r} est invalide. Valeurs acceptées : {', '.join(SETTINGS_BY_ENV)}."
        )
    return value


def configure_settings_module(default_env: str) -> str:
    environment = resolve_environment(default_env)
    explicit = os.environ.get("DJANGO_SETTINGS_MODULE")
    if explicit:
        if environment == "production" and explicit != SETTINGS_BY_ENV["production"]:
            raise ImproperlyConfigured(
                f"DJANGO_ENV=production mais DJANGO_SETTINGS_MODULE={explicit} : "
                "seuls les paramètres config.settings.prod sont autorisés en production."
            )
        return explicit
    os.environ["DJANGO_SETTINGS_MODULE"] = SETTINGS_BY_ENV[environment]
    return SETTINGS_BY_ENV[environment]
