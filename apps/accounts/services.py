"""Opérations métier sur les comptes."""

import logging
import smtplib

from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.conf import settings
from django.db import transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.core_errors import BusinessError, Forbidden
from apps.moderation.services import log_action

from .models import PUBLIC_SIGNUP_ROLES, Profile, Role, User

logger = logging.getLogger("ecourtier.accounts")


@transaction.atomic
def register_user(*, email: str, password: str, first_name: str, last_name: str, phone: str = "", role: str = Role.CUSTOMER) -> User:
    # Défense en profondeur : le serializer filtre déjà, mais le service ne fait jamais confiance à l'appelant.
    if role not in PUBLIC_SIGNUP_ROLES:
        raise Forbidden("Ce rôle ne peut pas être choisi lors de l'inscription.")
    if User.objects.filter(email__iexact=email).exists():
        raise BusinessError("Un compte existe déjà avec cette adresse e-mail.", code="email_taken")
    user = User.objects.create_user(
        email=email, password=password, first_name=first_name, last_name=last_name, phone=phone, role=role
    )
    Profile.objects.create(user=user)
    return user


@transaction.atomic
def change_role(*, actor: User, target: User, new_role: str) -> User:
    if not actor.is_admin:
        raise Forbidden("Seul un administrateur peut modifier un rôle.")
    if new_role not in Role.values:
        raise BusinessError("Rôle inconnu.")
    if actor.pk == target.pk:
        raise Forbidden("Un administrateur ne peut pas modifier son propre rôle.")
    old = target.role
    target.role = new_role
    target.is_staff = new_role == Role.ADMIN
    target.save(update_fields=["role", "is_staff"])
    log_action(actor=actor, action="user.role_changed", target=target, metadata={"from": old, "to": new_role})
    return target


@transaction.atomic
def set_active(*, actor: User, target: User, is_active: bool, reason: str = "") -> User:
    if not actor.is_admin:
        raise Forbidden("Action réservée aux administrateurs.")
    if actor.pk == target.pk:
        raise Forbidden("Vous ne pouvez pas désactiver votre propre compte.")
    target.is_active = is_active
    target.save(update_fields=["is_active"])
    log_action(
        actor=actor,
        action="user.activated" if is_active else "user.deactivated",
        target=target,
        metadata={"reason": reason[:200]},
    )
    return target


def request_password_reset(email: str) -> None:
    """Envoie un lien de réinitialisation si le compte existe. Ne révèle jamais son existence.

    Aucun envoi possible (service non configuré) → erreur explicite pour tous, avant toute recherche de compte.
    Échec du serveur d'envoi → erreur explicite plutôt qu'un faux « lien envoyé ». Le lien et le jeton ne sont
    jamais journalisés.
    """
    if not settings.EMAIL_ENABLED:
        raise BusinessError(
            "La réinitialisation par e-mail est momentanément indisponible. Contactez le support E-Courtier.",
            code="email_not_configured", http_status=503,
        )
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user:
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f"{settings.FRONTEND_URL}/reinitialiser-mot-de-passe?uid={uid}&token={token}"
    message = (
        f"Bonjour {user.first_name},\n\nPour choisir un nouveau mot de passe, ouvrez ce lien :\n{link}\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message."
    )
    try:
        send_mail(
            subject="E-Courtier — réinitialisation du mot de passe",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("Échec d'envoi de l'e-mail de réinitialisation (utilisateur %s) : %s", user.pk, type(exc).__name__)
        raise BusinessError(
            "L'e-mail de réinitialisation n'a pas pu être envoyé. Réessayez dans quelques minutes.",
            code="email_send_failed", http_status=503,
        )


def confirm_password_reset(*, uid: str, token: str, new_password: str) -> User:
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)), is_active=True)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        raise BusinessError("Lien de réinitialisation invalide ou expiré.", code="invalid_token")
    if not default_token_generator.check_token(user, token):
        raise BusinessError("Lien de réinitialisation invalide ou expiré.", code="invalid_token")
    user.set_password(new_password)
    user.save(update_fields=["password"])
    return user
