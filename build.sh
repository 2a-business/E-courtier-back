#!/usr/bin/env bash
# Commande de build (Render ou équivalent) : dépendances, contrôles, fichiers statiques, migrations.
set -euo pipefail
export DJANGO_ENV=production
export DJANGO_SETTINGS_MODULE=config.settings.prod
pip install -r requirements.txt
if [ "${STORAGE_BACKEND:-local}" = "s3" ]; then pip install -r requirements-s3.txt; fi
# Échoue si une variable de sécurité manque (prod.py) ou si un contrôle de déploiement est en erreur.
python manage.py check --deploy
python manage.py collectstatic --noinput
# Les migrations seront exécutées manuellement après validation de la cible
Neon.
