from django.apps import AppConfig


class AssistantConfig(AppConfig):
    name = "apps.assistant"
    label = "assistant"
    verbose_name = "Assistant IA"

    def ready(self):
        from . import checks  # noqa: F401  (enregistrement des contrôles système)
