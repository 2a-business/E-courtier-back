"""Configuration gunicorn (production Railway). Lancement : gunicorn config.wsgi:application -c gunicorn.conf.py

- Port fourni par Railway ($PORT), 8000 en local.
- Workers « gthread » : un appel LLM (jusqu'à LLM_TIMEOUT_SECONDS) ou la transmission d'une photo n'immobilise
  qu'un thread, pas tout le processus. Ajuster WEB_CONCURRENCY / GUNICORN_THREADS selon la mémoire du service.
- Journaux : messages informatifs sur stdout, avertissements et erreurs sur stderr (Railway classe stderr en erreur).
- Aucune migration ici : elles sont appliquées explicitement (voir RAILWAY_CONFIGURATION.md).
"""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
graceful_timeout = 20
keepalive = 5
# Recycle les workers périodiquement (fuites mémoire éventuelles des dépendances).
max_requests = 1000
max_requests_jitter = 100
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"below_warning": {"()": "config.log_filters.MaxLevelFilter", "level": "WARNING"}},
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "stdout": {"class": "logging.StreamHandler", "stream": "ext://sys.stdout", "formatter": "plain", "filters": ["below_warning"]},
        "stderr": {"class": "logging.StreamHandler", "stream": "ext://sys.stderr", "formatter": "plain", "level": "WARNING"},
    },
    # gunicorn fusionne ce dictionnaire avec sa configuration par défaut : la racine doit viser nos gestionnaires.
    "root": {"handlers": ["stdout", "stderr"], "level": "INFO"},
    "loggers": {
        "gunicorn.error": {"handlers": ["stdout", "stderr"], "level": loglevel.upper(), "propagate": False},
        # Avec logconfig_dict, gunicorn journalise chaque requête : doublon des HTTP Logs Railway, désactivé
        # par défaut (GUNICORN_ACCESS_LOG_LEVEL=INFO pour le réactiver).
        "gunicorn.access": {
            "handlers": ["stdout"], "level": os.environ.get("GUNICORN_ACCESS_LOG_LEVEL", "WARNING"), "propagate": False,
        },
    },
}
