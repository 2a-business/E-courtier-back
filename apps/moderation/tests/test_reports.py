import pytest

from apps.moderation.models import AuditLog
from conftest import client_for

pytestmark = pytest.mark.django_db


def test_report_flow_with_suspension(listing, customer, admin, api):
    c = client_for(customer)
    payload = {"listing": str(listing.pk), "reason": "FRAUD", "details": "Demande d'avance par WhatsApp"}
    res = c.post("/api/v1/reports/", payload, format="json")
    assert res.status_code == 201
    assert c.post("/api/v1/reports/", payload, format="json").status_code == 409
    assert client_for(listing.owner).post("/api/v1/reports/", payload, format="json").status_code == 400
    a = client_for(admin)
    assert a.get("/api/v1/admin/reports/", {"status": "OPEN"}).data["count"] == 1
    res = a.post(f"/api/v1/admin/reports/{res.data['id']}/", {"status": "RESOLVED", "note": "Annonce frauduleuse", "suspend_listing": True}, format="json")
    assert res.status_code == 200 and res.data["listing_status"] == "SUSPENDED"
    assert api.get(f"/api/v1/listings/{listing.pk}/").status_code == 404
    assert a.post(f"/api/v1/admin/reports/{res.data['id']}/", {"status": "DISMISSED"}, format="json").status_code == 409
    # Un nouveau signalement est possible une fois le précédent clos.
    assert AuditLog.objects.filter(action="report.resolved").exists()


def test_admin_endpoints_forbidden_to_others(customer, owner):
    for user in (customer, owner):
        c = client_for(user)
        for url in ("/api/v1/admin/dashboard/", "/api/v1/admin/reports/", "/api/v1/admin/audit-log/", "/api/v1/admin/users/",
                    "/api/v1/admin/verifications/", "/api/v1/admin/transactions/", "/api/v1/admin/assistant/usage/"):
            assert c.get(url).status_code == 403, url


def test_anonymous_cannot_reach_admin(api):
    assert api.get("/api/v1/admin/dashboard/").status_code == 401


def test_admin_dashboard(admin, listing):
    data = client_for(admin).get("/api/v1/admin/dashboard/").data
    assert data["listings_published"] == 1 and data["users_total"] == 2
