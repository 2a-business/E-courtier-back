"""Production : HTTPS obligatoire, secrets obligatoires, aucune simulation de paiement.

Le chargement échoue (ImproperlyConfigured) au lieu de démarrer avec une configuration incomplète ou dangereuse.
"""

from pathlib import Path
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

# --- Fichiers -----------------------------------------------------------------------
# Seuls les sous-dossiers publics (listings/) de MEDIA_ROOT sont diffusés. Les justificatifs peuvent vivre sur le
# même volume (<volume>/private), mais jamais à la racine des médias ni dans un sous-dossier public.
_media_root = Path(MEDIA_ROOT).resolve()  # noqa: F405
_private_root = Path(PRIVATE_MEDIA_ROOT).resolve()  # noqa: F405
_public_dirs = [_media_root / prefix for prefix in PUBLIC_MEDIA_PREFIXES]  # noqa: F405
_require(
    _private_root != _media_root
    and not _media_root.is_relative_to(_private_root)
    and not any(_private_root.is_relative_to(d) or d.is_relative_to(_private_root) for d in _public_dirs),
    "PRIVATE_MEDIA_ROOT ne doit être ni MEDIA_ROOT, ni un parent, ni un sous-dossier public "
    f"({', '.join(PUBLIC_MEDIA_PREFIXES)}/) : les justificatifs seraient publics.",  # noqa: F405
)

# --- E-mails ------------------------------------------------------------------------
# Jamais de backend console/fichier/mémoire en production : ils perdent les messages ou écrivent
# les liens de réinitialisation (jetons compris) dans les journaux.
EMAIL_BACKEND = env("EMAIL_BACKEND") or "django.core.mail.backends.smtp.EmailBackend"
_require(
    not any(name in EMAIL_BACKEND for name in ("console", "filebased", "locmem", "dummy")),
    f"EMAIL_BACKEND={EMAIL_BACKEND} est interdit en production (aucun envoi réel, jetons journalisés).",
)
_smtp = EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
EMAIL_ENABLED = bool(EMAIL_HOST) if _smtp else True  # noqa: F405
if EMAIL_ENABLED:
    _from = env("DEFAULT_FROM_EMAIL", "")
    _require(bool(_from), "DEFAULT_FROM_EMAIL est obligatoire dès qu'un serveur d'envoi est configuré.")
    _require(
        not _from.rstrip("> ").endswith((".local", "example.sn", "example.com")),
        "DEFAULT_FROM_EMAIL doit utiliser un domaine réel, autorisé par le fournisseur d'envoi.",
    )
    _require(not (EMAIL_USE_TLS and EMAIL_USE_SSL), "EMAIL_USE_TLS et EMAIL_USE_SSL sont exclusifs.")  # noqa: F405
    _require(
        not (_smtp and EMAIL_HOST_USER and not EMAIL_HOST_PASSWORD),  # noqa: F405
        "EMAIL_HOST_PASSWORD est obligatoire quand EMAIL_HOST_USER est défini.",
    )

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
