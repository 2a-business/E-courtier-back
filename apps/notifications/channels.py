"""Adaptateurs d'envoi SMS. Le backend actif est choisi par SMS_BACKEND."""

import logging
from typing import Protocol

from .models import SmsStatus

logger = logging.getLogger("ecourtier.sms")


class SMSBackend(Protocol):
    def send(self, phone: str, text: str) -> str:
        """Retourne un SmsStatus."""


class LoggingSMSBackend:
    """Développement : journalise le SMS sans l'envoyer. Le statut l'indique explicitement."""

    def send(self, phone: str, text: str) -> str:
        masked = f"{phone[:4]}******{phone[-2:]}" if len(phone) > 6 else "****"
        logger.info("SMS NON ENVOYÉ (backend de développement) vers %s : %s", masked, text[:160])
        return SmsStatus.LOGGED_NOT_SENT


class DisabledSMSBackend:
    def send(self, phone: str, text: str) -> str:
        return SmsStatus.NOT_REQUESTED
