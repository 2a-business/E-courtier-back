from django.apps import AppConfig


class MediaConfig(AppConfig):
    """Diffusion et contrôle des fichiers téléversés (aucun modèle : les métadonnées restent dans
    ListingPhoto et VerificationDocument, les fichiers physiques dans les stockages Django)."""

    name = "apps.media"
    label = "media"
    verbose_name = "Fichiers"

    def ready(self):
        from . import checks  # noqa: F401  (enregistrement des contrôles système)
