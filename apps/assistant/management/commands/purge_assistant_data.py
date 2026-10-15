from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.assistant.models import Conversation, DailyUsage, LLMCallLog


class Command(BaseCommand):
    help = "Supprime les conversations et journaux de l'assistant plus anciens que N jours (défaut 30)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args, days, **options):
        limit = timezone.now() - timedelta(days=days)
        n_conv, _ = Conversation.objects.filter(updated_at__lt=limit).delete()
        n_logs, _ = LLMCallLog.objects.filter(created_at__lt=limit).delete()
        n_usage, _ = DailyUsage.objects.filter(date__lt=limit.date() - timedelta(days=60)).delete()
        self.stdout.write(f"Supprimé : {n_conv} conversations, {n_logs} journaux, {n_usage} compteurs.")
