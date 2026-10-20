"""Paramètres communs à tous les environnements d'E-Courtier.

Les valeurs sensibles proviennent exclusivement des variables d'environnement.
Les modules ``dev``, ``test`` et ``prod`` surchargent ce fichier.
"""

from datetime import timedelta
from pathlib import Path
import os

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
# Fichier .env facultatif ; DJANGO_DOTENV_FILE permet d'en désigner un autre (ou un chemin inexistant pour l'ignorer).
DOTENV_FILE = Path(os.environ.get("DJANGO_DOTENV_FILE", BASE_DIR / ".env"))
load_dotenv(DOTENV_FILE)


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


ENVIRONMENT = env("DJANGO_ENV", "development")
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    "apps.accounts",
    "apps.media",
    "apps.moderation",
    "apps.notifications",
    "apps.listings",
    "apps.verification",
    "apps.search",
    "apps.assistant",
    "apps.visits",
    "apps.applications",
    "apps.transactions",
    "apps.contracts",
    "apps.reviews",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Base de données : PostgreSQL (Neon en production) via DATABASE_URL.
DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", "postgres://ecourtier:ecourtier@localhost:5432/ecourtier"),
        conn_max_age=env_int("DB_CONN_MAX_AGE", 60),
        conn_health_checks=True,
    )
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
# Dakar est en UTC+0 toute l'année (pas d'heure d'été). Les dates sont stockées en UTC.
TIME_ZONE = "Africa/Dakar"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = env("MEDIA_URL", "/media/")
# Volume persistant Railway monté sur /app/media (= BASE_DIR / "media", l'emplacement historique) : Railway fournit
# RAILWAY_VOLUME_MOUNT_PATH. Photos à la racine du volume (listings/<annonce>/<uuid>.jpg), justificatifs dans
# <volume>/private pour être eux aussi persistés (un seul volume par service). Seul le sous-dossier listings/ est
# diffusé publiquement (apps/media/views.py). MEDIA_ROOT / PRIVATE_MEDIA_ROOT explicites restent prioritaires.
VOLUME_ROOT = env("RAILWAY_VOLUME_MOUNT_PATH") or None
MEDIA_ROOT = Path(env("MEDIA_ROOT") or VOLUME_ROOT or BASE_DIR / "media")
# Justificatifs : stockage séparé, jamais exposé par une URL publique.
PRIVATE_MEDIA_ROOT = Path(
    env("PRIVATE_MEDIA_ROOT") or (Path(VOLUME_ROOT) / "private" if VOLUME_ROOT else BASE_DIR / "private_media")
)
# Sous-dossiers de MEDIA_ROOT diffusables sans authentification (liste blanche).
PUBLIC_MEDIA_PREFIXES = ("listings",)
# Durée de cache navigateur/CDN des photos publiques : les noms de fichiers sont uniques (uuid) et jamais réécrits.
MEDIA_CACHE_SECONDS = env_int("MEDIA_CACHE_SECONDS", 60 * 60 * 24 * 365)

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Stockage objet compatible S3 (Cloudflare R2, Backblaze B2, Supabase Storage…) optionnel.
if env("STORAGE_BACKEND", "local") == "s3":
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("S3_PUBLIC_BUCKET"),
            "endpoint_url": env("S3_ENDPOINT_URL"),
            "access_key": env("S3_ACCESS_KEY_ID"),
            "secret_key": env("S3_SECRET_ACCESS_KEY"),
            "custom_domain": env("S3_PUBLIC_DOMAIN") or None,
            "querystring_auth": False,
            "file_overwrite": False,
        },
    }
    STORAGES["private"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("S3_PRIVATE_BUCKET"),
            "endpoint_url": env("S3_ENDPOINT_URL"),
            "access_key": env("S3_ACCESS_KEY_ID"),
            "secret_key": env("S3_SECRET_ACCESS_KEY"),
            "default_acl": "private",
            "querystring_auth": True,
            "querystring_expire": 120,
            "file_overwrite": False,
        },
    }
else:
    STORAGES["private"] = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": str(PRIVATE_MEDIA_ROOT), "base_url": None},
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Téléversements
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
MAX_PHOTO_SIZE_MB = env_int("MAX_PHOTO_SIZE_MB", 5)
MAX_DOCUMENT_SIZE_MB = env_int("MAX_DOCUMENT_SIZE_MB", 8)
MAX_PHOTOS_PER_LISTING = env_int("MAX_PHOTOS_PER_LISTING", 12)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticatedOrReadOnly"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "config.pagination.StandardPagination",
    "PAGE_SIZE": 12,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", "300/hour"),
        "user": env("THROTTLE_USER", "2000/hour"),
        "auth": env("THROTTLE_AUTH", "10/minute"),
        "refresh": env("THROTTLE_REFRESH", "60/minute"),
        "register": env("THROTTLE_REGISTER", "10/hour"),
        "password_reset": env("THROTTLE_PASSWORD_RESET", "5/hour"),
        "assistant": env("THROTTLE_ASSISTANT", "8/minute"),
        "reports": env("THROTTLE_REPORTS", "10/day"),
        "uploads": env("THROTTLE_UPLOADS", "60/hour"),
    },
    "EXCEPTION_HANDLER": "config.exceptions.api_exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("JWT_ACCESS_MINUTES", 15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_DAYS", 7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# Le jeton de rafraîchissement vit dans un cookie HttpOnly ; le jeton d'accès reste en mémoire côté React.
REFRESH_COOKIE_NAME = "ec_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth/"
REFRESH_COOKIE_SECURE = env_bool("REFRESH_COOKIE_SECURE", True)
REFRESH_COOKIE_SAMESITE = env("REFRESH_COOKIE_SAMESITE", "Lax")

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:5173")
FRONTEND_URL = env("FRONTEND_URL", "http://localhost:5173")

SPECTACULAR_SETTINGS = {
    "TITLE": "API E-Courtier",
    "DESCRIPTION": "API REST v1 de la plateforme E-Courtier (recherche, location et achat de logements au Sénégal).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "ENUM_NAME_OVERRIDES": {
        "UserRoleEnum": "apps.accounts.models.Role",
        "PublicSignupRoleEnum": [("CUSTOMER", "Client"), ("OWNER", "Propriétaire")],
        "VisitStatusEnum": "apps.visits.models.VisitStatus",
        "TransactionStatusEnum": "apps.transactions.models.TransactionStatus",
        "ContractStatusEnum": "apps.contracts.models.ContractStatus",
        "ReportStatusEnum": "apps.moderation.models.ReportStatus",
        "VerificationRequestStatusEnum": "apps.verification.models.RequestStatus",
        "PublicationStatusEnum": "apps.listings.models.PublicationStatus",
        "ReviewStatusEnum": "apps.reviews.models.ReviewStatus",
        "AttemptStatusEnum": "apps.transactions.models.AttemptStatus",
        "ApplicationStatusEnum": "apps.applications.models.ApplicationStatus",
        "ApplicationDocumentTypeEnum": "apps.applications.models.ApplicationDocumentType",
        "VerificationDocumentTypeEnum": "apps.verification.models.DocumentType",
    },
}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "ecourtier"}}

EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "E-Courtier <no-reply@e-courtier.local>")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
# Sans délai, une connexion SMTP bloquée immobiliserait un worker gunicorn indéfiniment.
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 10)
# Faux en production tant qu'aucun serveur SMTP n'est configuré (voir prod.py) : les envois sont alors refusés
# explicitement au lieu d'être perdus.
EMAIL_ENABLED = True

# --- Règles métier configurables -------------------------------------------------
CURRENCY = "XOF"
DOSSIER_FEE_XOF = env_int("DOSSIER_FEE_XOF", 5000)
SALE_DEPOSIT_PERCENT = env_int("SALE_DEPOSIT_PERCENT", 10)

# --- Dossier locatif -------------------------------------------------------------
# Pièces obligatoires avant transmission : groupes séparés par des virgules, alternatives par « | ».
# Défaut : une pièce d'identité (CNI ou passeport). Ex. « ID_CARD|PASSPORT,INCOME_PROOF|EMPLOYMENT_PROOF ».
RENTAL_APPLICATION_REQUIRED_DOCS = [set(group.split("|")) for group in env_list("RENTAL_APPLICATION_REQUIRED_DOCS", "ID_CARD|PASSPORT")]
MAX_APPLICATION_DOCUMENTS = env_int("MAX_APPLICATION_DOCUMENTS", 15)

# --- Paiement -------------------------------------------------------------------
# Lien de paiement Wave Business (marchand). Le client y saisit le montant puis confirme dans son appli.
WAVE_PAYMENT_LINK = env("WAVE_PAYMENT_LINK", "")
# Lien facultatif dédié aux frais de dossier (souvent un lien à montant fixe) ; à défaut, WAVE_PAYMENT_LINK.
WAVE_DOSSIER_FEE_LINK = env("WAVE_DOSSIER_FEE_LINK", "")
# La simulation est interdite en production (voir prod.py).
PAYMENT_SIMULATION_ENABLED = env_bool("PAYMENT_SIMULATION_ENABLED", False)

# --- Notifications --------------------------------------------------------------
SMS_BACKEND = env("SMS_BACKEND", "apps.notifications.channels.LoggingSMSBackend")

# --- Assistant IA ---------------------------------------------------------------
LLM_PROVIDER = env("LLM_PROVIDER", "rules")  # gemini | groq | rules
LLM_MODEL = env("LLM_MODEL", "")
LLM_API_KEY = env("LLM_API_KEY", "")
LLM_TIMEOUT_SECONDS = float(env("LLM_TIMEOUT_SECONDS", "8"))
LLM_MAX_OUTPUT_TOKENS = env_int("LLM_MAX_OUTPUT_TOKENS", 256)
LLM_MAX_RETRIES = env_int("LLM_MAX_RETRIES", 1)
LLM_COOLDOWN_SECONDS = env_int("LLM_COOLDOWN_SECONDS", 60)
ASSISTANT_GLOBAL_DAILY_REQUESTS = env_int("ASSISTANT_GLOBAL_DAILY_REQUESTS", 120)
ASSISTANT_GLOBAL_DAILY_PROVIDER_CALLS = env_int("ASSISTANT_GLOBAL_DAILY_PROVIDER_CALLS", 200)
ASSISTANT_USER_DAILY_REQUESTS = env_int("ASSISTANT_USER_DAILY_REQUESTS", 20)
ASSISTANT_ANON_DAILY_REQUESTS = env_int("ASSISTANT_ANON_DAILY_REQUESTS", 10)
ASSISTANT_HISTORY_MESSAGES = env_int("ASSISTANT_HISTORY_MESSAGES", 4)
ASSISTANT_MAX_MESSAGE_CHARS = env_int("ASSISTANT_MAX_MESSAGE_CHARS", 500)
ASSISTANT_RESULTS_LIMIT = env_int("ASSISTANT_RESULTS_LIMIT", 6)

# Railway classe en erreur tout ce qui sort sur stderr : INFO → stdout, WARNING et plus → stderr.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"below_warning": {"()": "config.log_filters.MaxLevelFilter", "level": "WARNING"}},
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "stdout": {"class": "logging.StreamHandler", "stream": "ext://sys.stdout", "formatter": "plain", "filters": ["below_warning"]},
        "stderr": {"class": "logging.StreamHandler", "stream": "ext://sys.stderr", "formatter": "plain", "level": "WARNING"},
    },
    "root": {"handlers": ["stdout", "stderr"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {"django.request": {"level": "WARNING"}},
}
LLM_GEMINI_DISABLE_THINKING = env_bool("LLM_GEMINI_DISABLE_THINKING", True)
