import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.accounts.models import Role, User
from conftest import client_for, make_user

pytestmark = pytest.mark.django_db
AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


def register(api, **extra):
    payload = {"email": "Awa@Exemple.sn", "password": "Teranga-2026!", "first_name": "Awa", "last_name": "Diop"} | extra
    return api.post("/api/v1/auth/register/", payload, format="json")


def test_register_creates_customer_and_sets_httponly_refresh_cookie(api):
    res = register(api)
    assert res.status_code == 201
    assert res.data["user"]["role"] == "CUSTOMER"
    assert res.data["user"]["email"] == "awa@exemple.sn"
    cookie = res.cookies["ec_refresh"]
    assert cookie["httponly"] and cookie["path"] == "/api/v1/auth/"
    assert "refresh" not in res.data


@pytest.mark.parametrize("role", ["ADMIN", "AGENT"])
def test_public_signup_cannot_grant_privileged_roles(api, role):
    res = register(api, role=role)
    assert res.status_code == 400
    assert not User.objects.filter(role=role).exists()


def test_owner_signup_allowed(api):
    assert register(api, role="OWNER").data["user"]["role"] == "OWNER"


def test_duplicate_email_rejected(api):
    register(api)
    res = register(api, email="awa@exemple.sn")
    assert res.status_code == 400 and res.data["code"] == "email_taken"


def test_weak_password_rejected(api):
    assert register(api, password="12345678").status_code == 400


def test_user_cannot_change_own_role_via_profile(customer):
    res = client_for(customer).patch("/api/v1/auth/me/", {"role": "ADMIN", "first_name": "Nouveau"}, format="json")
    assert res.status_code == 200
    customer.refresh_from_db()
    assert customer.role == Role.CUSTOMER and customer.first_name == "Nouveau"


def test_login_refresh_rotation_and_logout(api):
    register(api)
    api.cookies.clear()
    res = api.post("/api/v1/auth/login/", {"email": "awa@exemple.sn", "password": "Teranga-2026!"}, format="json")
    assert res.status_code == 200 and res.data["access"]
    old_refresh = res.cookies["ec_refresh"].value
    assert api.post("/api/v1/auth/refresh/").status_code == 403  # en-tête anti-CSRF manquant
    res = api.post("/api/v1/auth/refresh/", **AJAX)
    assert res.status_code == 200 and res.cookies["ec_refresh"].value != old_refresh
    # L'ancien jeton a été mis en liste noire (rotation).
    api.cookies["ec_refresh"] = old_refresh
    assert api.post("/api/v1/auth/refresh/", **AJAX).status_code == 401
    assert api.post("/api/v1/auth/logout/", **AJAX).status_code == 204


def test_wrong_password(api):
    register(api)
    res = api.post("/api/v1/auth/login/", {"email": "awa@exemple.sn", "password": "mauvais"}, format="json")
    assert res.status_code == 401


def test_password_reset_does_not_reveal_accounts_and_works(api, customer):
    assert api.post("/api/v1/auth/password-reset/", {"email": "inconnu@test.sn"}, format="json").status_code == 202
    assert len(mail.outbox) == 0
    api.post("/api/v1/auth/password-reset/", {"email": customer.email}, format="json")
    assert len(mail.outbox) == 1
    uid = urlsafe_base64_encode(force_bytes(customer.pk))
    token = default_token_generator.make_token(customer)
    res = api.post("/api/v1/auth/password-reset/confirm/", {"uid": uid, "token": token, "new_password": "Nouveau-mdp-2026"}, format="json")
    assert res.status_code == 200
    customer.refresh_from_db()
    assert customer.check_password("Nouveau-mdp-2026")
    res = api.post("/api/v1/auth/password-reset/confirm/", {"uid": uid, "token": token, "new_password": "Encore-autre-2026"}, format="json")
    assert res.status_code == 400


def test_password_reset_email_content(api, customer, settings):
    settings.FRONTEND_URL = "https://front.exemple.sn"
    settings.DEFAULT_FROM_EMAIL = "E-Courtier <no-reply@e-courtier.sn>"
    assert api.post("/api/v1/auth/password-reset/", {"email": customer.email.upper()}, format="json").status_code == 202
    message = mail.outbox[0]
    assert message.to == [customer.email] and message.from_email == "E-Courtier <no-reply@e-courtier.sn>"
    assert f"https://front.exemple.sn/reinitialiser-mot-de-passe?uid={urlsafe_base64_encode(force_bytes(customer.pk))}&token=" in message.body


def test_password_reset_refused_explicitly_when_email_disabled(api, customer, settings):
    settings.EMAIL_ENABLED = False
    for email in (customer.email, "inconnu@test.sn"):  # même réponse : l'existence du compte n'est pas révélée
        res = api.post("/api/v1/auth/password-reset/", {"email": email}, format="json")
        assert res.status_code == 503 and res.data["code"] == "email_not_configured"
    assert len(mail.outbox) == 0


def test_password_reset_smtp_failure_is_reported_without_leaking_token(api, customer, monkeypatch, caplog):
    import smtplib

    from apps.accounts import services

    def broken(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"refus")

    monkeypatch.setattr(services, "send_mail", broken)
    res = api.post("/api/v1/auth/password-reset/", {"email": customer.email}, format="json")
    assert res.status_code == 503 and res.data["code"] == "email_send_failed"
    token = default_token_generator.make_token(customer)
    assert "SMTPAuthenticationError" in caplog.text
    assert token not in caplog.text and "reinitialiser-mot-de-passe" not in caplog.text and customer.email not in caplog.text


def test_admin_role_management(admin, customer):
    assert client_for(customer).post(f"/api/v1/admin/users/{customer.pk}/role/", {"role": "ADMIN"}, format="json").status_code == 403
    res = client_for(admin).post(f"/api/v1/admin/users/{customer.pk}/role/", {"role": "AGENT"}, format="json")
    assert res.status_code == 200 and res.data["role"] == "AGENT"
    assert client_for(admin).post(f"/api/v1/admin/users/{admin.pk}/role/", {"role": "CUSTOMER"}, format="json").status_code == 403


def test_admin_deactivate_user_blocks_login(api, admin):
    user = make_user(email="bloque@test.sn")
    client_for(admin).post(f"/api/v1/admin/users/{user.pk}/active/", {"is_active": False, "reason": "fraude"}, format="json")
    res = api.post("/api/v1/auth/login/", {"email": "bloque@test.sn", "password": "Motdepasse-solide-1"}, format="json")
    assert res.status_code == 401
