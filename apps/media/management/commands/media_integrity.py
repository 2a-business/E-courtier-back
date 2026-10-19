"""Vérifie, en lecture seule, que chaque fichier référencé en base existe dans son stockage.

Usage : python manage.py media_integrity [--details]
N'écrit ni ne supprime rien. Code de sortie 1 si des fichiers manquent (utilisable en contrôle post-déploiement).
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.listings.models import ListingPhoto
from apps.verification.models import VerificationDocument


class Command(BaseCommand):
    help = "Contrôle l'existence des photos et justificatifs référencés en base (lecture seule)."

    def add_arguments(self, parser):
        parser.add_argument("--details", action="store_true", help="Liste les identifiants des éléments incomplets.")

    def handle(self, *args, details=False, **options):
        self.stdout.write(f"Photos publiques : {settings.MEDIA_ROOT}")
        self.stdout.write(f"Justificatifs privés : {settings.PRIVATE_MEDIA_ROOT}")
        missing_total = 0

        photos = ListingPhoto.objects.only("id", "listing_id", "image", "thumbnail").order_by("id")
        broken = []
        for photo in photos.iterator():
            absent = [f.field.name for f in (photo.image, photo.thumbnail) if f.name and not f.storage.exists(f.name)]
            if absent:
                broken.append((photo, absent))
        self.stdout.write(f"Photos : {photos.count()} en base, {len(broken)} avec fichier(s) manquant(s)")
        if details:
            for photo, absent in broken:
                self.stdout.write(f"  photo {photo.pk} (annonce {photo.listing_id}) : {', '.join(absent)}")
        missing_total += len(broken)

        documents = VerificationDocument.objects.only("id", "listing_id", "file").order_by("id")
        broken_docs = [d for d in documents.iterator() if d.file.name and not d.file.storage.exists(d.file.name)]
        # Le nom de fichier d'origine n'est jamais affiché (donnée personnelle possible).
        self.stdout.write(f"Justificatifs : {documents.count()} en base, {len(broken_docs)} fichier(s) manquant(s)")
        if details:
            for doc in broken_docs:
                self.stdout.write(f"  justificatif {doc.pk} (annonce {doc.listing_id})")
        missing_total += len(broken_docs)

        if missing_total:
            raise CommandError(f"{missing_total} élément(s) sans fichier physique.")
        self.stdout.write(self.style.SUCCESS("Tous les fichiers référencés sont présents."))
