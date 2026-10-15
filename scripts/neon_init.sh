#!/usr/bin/env bash
# Initialisation d'une base Neon : contrôle de la cible, plan de migration, migrations, compte administrateur.
#
# Prérequis : un fichier d'environnement de production NON versionné (ex. backend/.env.production.local,
# couvert par « .env.* » dans .gitignore) contenant DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS,
# CORS_ALLOWED_ORIGINS, CSRF_TRUSTED_ORIGINS, FRONTEND_URL, PAYMENT_SIMULATION_ENABLED=false et
# DATABASE_URL_DIRECT (URL Neon DIRECTE, sans « -pooler », avec ?sslmode=require).
#
# Usage : scripts/neon_init.sh .env.production.local ep-xxxx.eu-central-1.aws.neon.tech [ecourtier]
set -euo pipefail

USAGE="Usage : scripts/neon_init.sh <fichier-env-production> <hote-neon-direct> [base]"
ENV_FILE="${1:-}"
EXPECTED_HOST="${2:-}"
if [ -z "$ENV_FILE" ] || [ -z "$EXPECTED_HOST" ]; then echo "$USAGE" >&2; exit 1; fi
EXPECTED_DB="${3:-ecourtier}"
# Chemin résolu AVANT le changement de dossier (le script peut être lancé depuis n'importe où).
[ -f "$ENV_FILE" ] || { echo "Fichier introuvable : $ENV_FILE" >&2; exit 1; }
ENV_FILE="$(cd "$(dirname "$ENV_FILE")" && pwd)/$(basename "$ENV_FILE")"
case "$(basename "$ENV_FILE")" in
  *.example) echo "Refus : $ENV_FILE est un modèle versionné." >&2; exit 1;;
  .env) echo "Refus : $ENV_FILE est le fichier de développement local ; utilisez un fichier de production dédié." >&2; exit 1;;
esac
cd "$(dirname "$0")/.."

# Paramètres de production uniquement, à partir de ce seul fichier (le backend/.env local est ignoré).
export DJANGO_ENV=production
export DJANGO_SETTINGS_MODULE=config.settings.prod
export DJANGO_DOTENV_FILE="$ENV_FILE"
unset DATABASE_URL TEST_DATABASE_URL || true
DIRECT_URL="$(ENV_FILE="$ENV_FILE" python -c 'import os; from dotenv import dotenv_values as d; print(d(os.environ["ENV_FILE"]).get("DATABASE_URL_DIRECT") or "")')"
[ -n "$DIRECT_URL" ] || { echo "DATABASE_URL_DIRECT manquante dans $ENV_FILE" >&2; exit 1; }
export DATABASE_URL="$DIRECT_URL"

echo "== 1. Cible (aucune donnée modifiée) =="
python manage.py db_target --expect-host "$EXPECTED_HOST" --expect-database "$EXPECTED_DB" --expect-direct --expect-production
python manage.py check --deploy

echo "== 2. Plan des migrations (lecture seule) =="
# Toute erreur (connexion refusée, SSL, authentification) arrête le script ici, avant toute écriture.
python manage.py migrate --plan
SHOWMIGRATIONS="$(python manage.py showmigrations --plan)"
APPLIED="$(printf '%s\n' "$SHOWMIGRATIONS" | grep -c '\[X\]' || true)"
TABLES="$(python manage.py shell --no-imports -c 'from django.db import connection; print(len(connection.introspection.table_names()))')"
echo "Migrations déjà appliquées : $APPLIED — tables existantes : $TABLES"
if [ "$APPLIED" -gt 0 ] || [ "$TABLES" -gt 0 ]; then
  echo "ATTENTION : la base n'est pas vide. Vérifiez qu'il s'agit bien de la base E-Courtier attendue."
  read -r -p "Tapez « BASE EXISTANTE » pour continuer, autre chose pour arrêter : " ANSWER
  [ "$ANSWER" = "BASE EXISTANTE" ] || { echo "Arrêt."; exit 1; }
fi

read -r -p "Appliquer ces migrations sur $EXPECTED_HOST/$EXPECTED_DB ? Retapez l'hôte pour confirmer : " ANSWER
[ "$ANSWER" = "$EXPECTED_HOST" ] || { echo "Confirmation incorrecte, arrêt."; exit 1; }

echo "== 3. Migrations =="
python manage.py migrate --noinput
python manage.py migrate --check && echo "Aucune migration en attente."

echo "== 4. Compte administrateur (rôle ADMIN) =="
read -r -p "Créer maintenant le compte administrateur ? [o/N] " ANSWER
if [ "$ANSWER" = "o" ] || [ "$ANSWER" = "O" ]; then
  python manage.py createsuperuser
fi
echo "Terminé. Côté hébergeur, DATABASE_URL doit rester l'URL POOLED."
