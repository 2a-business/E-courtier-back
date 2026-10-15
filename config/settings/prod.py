"""Production : HTTPS obligatoire, secrets obligatoires, aucune simulation de paiement.

Le chargement échoue (ImproperlyConfigured) au lieu de démarrer avec une configuration incomplète ou dangereuse.
"""

from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import env, env_bool, env_int, env_list

# Quel que soit DJANGO_ENV, ces paramètres sont ceux de la production (seed_demo et consorts s'y fient).
ENVIRONMENT = "production"
DEBUG = False


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ImproperlyConfigured(message)


# --- Secrets et hôtes -------------------------------------------------------------
_require(bool(SECRET_KEY), "DJANGO_SECRET_KEY est obligatoire en production.")  # noqa: F405
_require(
    len(SECRET_KEY) >= 40  # noqa: F405
    and len(set(SECRET_KEY)) >= 5  # noqa: F405
    and not SECRET_KEY.startswith(("dev-only", "django-insecure", "test-secret")),  # noqa: F405
    "DJANGO_SECRET_KEY est trop faible ou provient d'un environnement de développement (40 caractères aléatoires minimum).",
)
_require(bool(env("DJANGO_ALLOWED_HOSTS")), "DJANGO_ALLOWED_HOSTS est obligatoire en production.")
_require("*" not in ALLOWED_HOSTS, "DJANGO_ALLOWED_HOSTS ne doit pas contenir « * » en production.")  # noqa: F405

# Origines du frontend : explicites et en HTTPS, jamais les valeurs locales par défaut.
for _name in ("CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS", "FRONTEND_URL"):
    _values = env_list(_name)
    _require(bool(_values), f"{_name} est obligatoire en production.")
    _require(all(v.startswith("https://") for v in _values), f"{_name} doit contenir uniquement des URL https://.")

# --- Base de données ----------------------------------------------------------------
_database_url = env("DATABASE_URL")
_require(bool(_database_url), "DATABASE_URL est obligatoire en production.")
_db = DATABASES["default"]  # noqa: F405
_require(_db["ENGINE"] == "django.db.backends.postgresql", "La production exige PostgreSQL.")
_require(
    not str(_db.get("NAME", "")).startswith("test_") and _database_url != env("TEST_DATABASE_URL"),
    "DATABASE_URL désigne une base de test : refus de démarrer en production.",
)
if (_db.get("HOST") or "") not in ("localhost", "127.0.0.1", ""):
    # Base distante (Neon…) : chiffrement obligatoire.
    _require(
        _db.get("OPTIONS", {}).get("sslmode") in {"require", "verify-ca", "verify-full"},
        "DATABASE_URL distante sans ?sslmode=require : connexion non chiffrée refusée.",
    )

# --- Paiement -----------------------------------------------------------------------
# La simulation de paiement ne doit jamais être active sur un environnement réel.
_require(not PAYMENT_SIMULATION_ENABLED, "PAYMENT_SIMULATION_ENABLED doit être false en production.")  # noqa: F405
if WAVE_PAYMENT_LINK:  # noqa: F405
    _require(urlparse(WAVE_PAYMENT_LINK).scheme == "https", "WAVE_PAYMENT_LINK doit être une URL https://.")  # noqa: F405

# --- HTTPS et cookies ---------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
REFRESH_COOKIE_SECURE = True
# Frontend et backend sur des domaines distincts : le cookie de rafraîchissement doit être SameSite=None.
REFRESH_COOKIE_SAMESITE = env("REFRESH_COOKIE_SAMESITE", "None")
