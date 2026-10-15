import pytest
from django.test import override_settings

from apps.notifications.models import SmsStatus
from apps.notifications.services import notify
from conftest import client_for, make_user

pytestmark = pytest.mark.django_db


def test_dev_sms_backend_never_claims_sent(caplog):
    user = make_user(phone="+221 77 123 45 67")
    with caplog.at_level("INFO", logger="ecourtier.sms"):
        n = notify(user, kind="t", title="Visite confirmée", body="x", sms=True)
    assert n.sms_status == SmsStatus.LOGGED_NOT_SENT
    assert "77 123 45 67" not in caplog.text  # numéro masqué


def test_no_phone_and_disabled_backend():
    user = make_user()
    assert notify(user, kind="t", title="a", body="b", sms=True).sms_status == SmsStatus.NO_PHONE
    with override_settings(SMS_BACKEND="apps.notifications.channels.DisabledSMSBackend"):
        user.phone = "771234567"
        assert notify(user, kind="t", title="a", body="b", sms=True).sms_status == SmsStatus.NOT_REQUESTED


def test_list_and_mark_read():
    user = make_user()
    notify(user, kind="t", title="a", body="b")
    notify(make_user(), kind="t", title="autre", body="b")
    c = client_for(user)
    assert c.get("/api/v1/notifications/unread-count/").data["unread"] == 1
    assert c.get("/api/v1/notifications/").data["count"] == 1
    c.post("/api/v1/notifications/read/", {}, format="json")
    assert c.get("/api/v1/notifications/unread-count/").data["unread"] == 0
