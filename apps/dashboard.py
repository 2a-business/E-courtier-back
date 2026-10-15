"""Agrégats en lecture seule pour les tableaux de bord (propriétaire/agent et administration)."""

from datetime import timedelta

from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.accounts.models import User
from apps.listings.models import Listing
from apps.moderation.models import Report
from apps.reviews.models import Review
from apps.transactions.models import Transaction
from apps.verification.models import VerificationRequest
from apps.visits.models import Visit


def _daily(qs, field: str, days: int = 30):
    start = timezone.now() - timedelta(days=days - 1)
    rows = dict(
        qs.filter(**{f"{field}__gte": start}).annotate(day=TruncDate(field)).values_list("day").annotate(n=Count("pk"))
    )
    today = timezone.localdate()
    return [
        {"date": (today - timedelta(days=i)).isoformat(), "count": rows.get(today - timedelta(days=i), 0)}
        for i in range(days - 1, -1, -1)
    ]


def owner_stats(user) -> dict:
    listings = Listing.objects.filter(owner=user)
    by_status = dict(listings.values_list("publication_status").annotate(n=Count("id")))
    by_verif = dict(listings.values_list("verification_status").annotate(n=Count("id")))
    visits = Visit.objects.filter(host=user)
    now = timezone.now()
    reviews = Review.objects.filter(listing__owner=user, status="PUBLISHED").aggregate(avg=Avg("rating"), n=Count("id"))
    paid = Transaction.objects.filter(owner=user, status="PAID")
    return {
        "listings_total": listings.count(),
        "listings_by_status": by_status,
        "listings_by_verification": by_verif,
        "visits_pending": visits.filter(status="PENDING").count(),
        "visits_upcoming": visits.filter(status="CONFIRMED", slot__starts_at__gte=now).count(),
        "visits_completed": visits.filter(status="COMPLETED").count(),
        "transactions_pending": Transaction.objects.filter(owner=user, status="PENDING").count(),
        "transactions_paid": paid.filter(is_simulated=False).count(),
        "transactions_paid_simulated": paid.filter(is_simulated=True).count(),
        "reviews_count": reviews["n"],
        "reviews_average": round(reviews["avg"], 1) if reviews["avg"] else None,
        "visit_requests_daily": _daily(visits, "created_at"),
    }


def admin_stats() -> dict:
    tx = Transaction.objects.all()
    return {
        "users_total": User.objects.count(),
        "users_by_role": dict(User.objects.values_list("role").annotate(n=Count("id"))),
        "listings_total": Listing.objects.count(),
        "listings_published": Listing.objects.filter(publication_status="PUBLISHED").count(),
        "listings_suspended": Listing.objects.filter(publication_status="SUSPENDED").count(),
        "verifications_pending": VerificationRequest.objects.filter(status="PENDING").count(),
        "reports_open": Report.objects.filter(status__in=["OPEN", "IN_REVIEW"]).count(),
        "transactions_pending": tx.filter(status="PENDING").count(),
        "transactions_to_check": tx.filter(status="PENDING", attempts__status="CUSTOMER_DECLARED").distinct().count(),
        "transactions_paid": tx.filter(status="PAID", is_simulated=False).count(),
        "transactions_paid_simulated": tx.filter(status="PAID", is_simulated=True).count(),
        "fees_collected_real": tx.filter(status="PAID", is_simulated=False).aggregate(s=Sum("fee_amount"))["s"] or 0,
        "visits_total": Visit.objects.count(),
        "listings_daily": _daily(Listing.objects.all(), "created_at"),
        "visits_daily": _daily(Visit.objects.all(), "created_at"),
        "verified_ratio": _ratio(Listing.objects.filter(publication_status="PUBLISHED")),
    }


def _ratio(qs):
    total = qs.count()
    return round(qs.filter(verification_status="APPROVED").count() / total, 3) if total else None
