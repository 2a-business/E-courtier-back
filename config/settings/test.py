"""Tests automatisés : PostgreSQL si TEST_DATABASE_URL est fourni, sinon SQLite en mémoire.

Garde-fous : jamais en production, jamais sur la base de l'application, jamais sur une base distante
(Neon…) sauf autorisation explicite ALLOW_REMOTE_TEST_DATABASE=true — pytest crée puis SUPPRIME la base de test.
"""

import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import ENVIRONMENT, env_bool

if ENVIRONMENT == "production":
    raise ImproperlyConfigured("DJANGO_ENV=production : les paramètres de test sont interdits.")

DEBUG = False
SECRET_KEY = "test-secret-key-not-for-production"
_test_url = os.environ.get("TEST_DATABASE_URL")
if _test_url:
    if _test_url == os.environ.get("DATABASE_URL"):
        raise ImproperlyConfigured("TEST_DATABASE_URL ne doit pas être identique à DATABASE_URL.")
    _test_db = dj_database_url.parse(_test_url)
    if _test_db.get("HOST") not in ("localhost", "127.0.0.1", "", None) and not env_bool("ALLOW_REMOTE_TEST_DATABASE"):
        raise ImproperlyConfigured(
            "TEST_DATABASE_URL pointe vers un serveur distant. Les tests créent et suppriment des bases : "
            "utilisez PostgreSQL local, ou une branche Neon jetable avec ALLOW_REMOTE_TEST_DATABASE=true."
        )
    # Même avec l'autorisation ci-dessus, jamais le serveur de l'application (pooled ou direct).
    def _endpoint(url):
        return (dj_database_url.parse(url).get("HOST") or "").replace("-pooler", "") if url else None

    _app_endpoints = {_endpoint(os.environ.get(k)) for k in ("DATABASE_URL", "DATABASE_URL_DIRECT")} - {None, ""}
    if _test_db.get("HOST") not in ("localhost", "127.0.0.1", "", None) and _endpoint(_test_url) in _app_endpoints:
        raise ImproperlyConfigured("TEST_DATABASE_URL vise le même serveur que DATABASE_URL : refusé.")
    DATABASES = {"default": _test_db}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
REFRESH_COOKIE_SECURE = False
PAYMENT_SIMULATION_ENABLED = True
WAVE_PAYMENT_LINK = "https://pay.wave.com/m/M_test_ecourtier/c/sn/"
LLM_PROVIDER = "rules"
LLM_API_KEY = ""
MEDIA_ROOT = BASE_DIR / ".test_media"  # noqa: F405
PRIVATE_MEDIA_ROOT = BASE_DIR / ".test_private_media"  # noqa: F405
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": str(MEDIA_ROOT)}},
    "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": str(PRIVATE_MEDIA_ROOT)}},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
REST_FRAMEWORK = {**REST_FRAMEWORK}  # noqa: F405
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
    "anon": "10000/minute",
    "user": "10000/minute",
    "auth": "1000/minute",
    "refresh": "1000/minute",
    "register": "1000/minute",
    "assistant": "1000/minute",
    "reports": "1000/minute",
    "uploads": "1000/minute",
}
SMS_BACKEND = "apps.notifications.channels.LoggingSMSBackend"

MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405
