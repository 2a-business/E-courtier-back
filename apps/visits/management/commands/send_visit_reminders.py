from django.core.management.base import BaseCommand

from apps.visits.services import send_due_reminders


class Command(BaseCommand):
    help = "Envoie les rappels des visites confirmées dans les prochaines 24 h (à planifier, ex. toutes les heures)."

    def handle(self, *args, **options):
        self.stdout.write(f"{send_due_reminders()} rappel(s) envoyé(s).")
