"""Affiche la base de données réellement ciblée, sans secret, avant une opération sensible.

    python manage.py db_target
    python manage.py db_target --expect-host ep-xxx.eu-central-1.aws.neon.tech --expect-direct

Avec --expect-*, la commande échoue (code 1) si la cible ne correspond pas : à placer avant migrate /
createsuperuser pour éviter de viser la mauvaise base (test, pooler, autre projet…).
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Affiche la base ciblée (hôte, base, utilisateur, SSL, pooler) sans mot de passe."

    def add_arguments(self, parser):
        parser.add_argument("--expect-host", help="Hôte attendu (exact).")
        parser.add_argument("--expect-database", help="Nom de base attendu.")
        parser.add_argument("--expect-direct", action="store_true", help="Exige une connexion directe (hors pooler Neon).")
        parser.add_argument("--expect-production", action="store_true", help="Exige les paramètres de production.")

    def handle(self, *args, expect_host=None, expect_database=None, expect_direct=False, expect_production=False, **options):
        db = settings.DATABASES["default"]
        host = db.get("HOST") or "(socket local)"
        pooled = "-pooler" in host
        rows = [
            ("Paramètres", settings.SETTINGS_MODULE),
            ("Environnement", settings.ENVIRONMENT),
            ("DEBUG", settings.DEBUG),
            ("Moteur", db["ENGINE"].rsplit(".", 1)[-1]),
            ("Hôte", host),
            ("Base", db.get("NAME")),
            ("Utilisateur", db.get("USER") or "-"),
            ("SSL", db.get("OPTIONS", {}).get("sslmode", "non précisé")),
            ("Connexion", "pooled (pooler Neon)" if pooled else "directe"),
            ("Neon", "oui" if host.endswith(".neon.tech") else "non"),
        ]
        for label, value in rows:
            self.stdout.write(f"{label:>14} : {value}")

        problems = []
        if expect_host and host != expect_host:
            problems.append(f"hôte {host!r} différent de l'hôte attendu {expect_host!r}")
        if expect_database and db.get("NAME") != expect_database:
            problems.append(f"base {db.get('NAME')!r} différente de {expect_database!r}")
        if expect_direct and pooled:
            problems.append("connexion via le pooler : utilisez l'URL directe pour les migrations")
        if expect_production and settings.ENVIRONMENT != "production":
            problems.append("les paramètres de production ne sont pas chargés")
        if str(db.get("NAME", "")).startswith("test_"):
            problems.append("la base ressemble à une base de test")
        if connection.vendor == "sqlite":
            problems.append("SQLite : ce n'est pas une base PostgreSQL")
        if problems:
            raise CommandError("Cible refusée : " + " ; ".join(problems))
        if any((expect_host, expect_database, expect_direct, expect_production)):
            self.stdout.write(self.style.SUCCESS("Cible conforme aux attentes."))
