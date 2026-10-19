from django.apps import AppConfig


class ApplicationsConfig(AppConfig):
    name = "apps.applications"
    label = "applications"
    verbose_name = "Dossiers locatifs"

    def ready(self):
        from . import checks  # noqa: F401  (enregistrement des contrôles système)
