"""Développement local."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import ENVIRONMENT, env_bool

# Garde-fou : ces paramètres (DEBUG, simulation de paiement, clé de repli) ne doivent jamais servir en production.
if ENVIRONMENT == "production":
    raise ImproperlyConfigured(
        "DJANGO_ENV=production : les paramètres de développement sont interdits. Utilisez config.settings.prod."
    )

DEBUG = True
SECRET_KEY = SECRET_KEY or "dev-only-insecure-key-ne-pas-utiliser-en-production"  # noqa: F405
REFRESH_COOKIE_SECURE = env_bool("REFRESH_COOKIE_SECURE", False)
PAYMENT_SIMULATION_ENABLED = env_bool("PAYMENT_SIMULATION_ENABLED", True)
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
