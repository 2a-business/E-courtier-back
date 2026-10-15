from django.db.models import Avg, Count, Prefetch, Q

from .models import Listing, ListingPhoto, PublicationStatus


def primary_photo_prefetch():
    return Prefetch("photos", queryset=ListingPhoto.objects.order_by("-is_primary", "position", "id"))


def public_listings():
    return Listing.objects.filter(publication_status=PublicationStatus.PUBLISHED)


def card_queryset(qs=None):
    qs = public_listings() if qs is None else qs
    return qs.select_related("owner").prefetch_related(primary_photo_prefetch())


def detail_queryset():
    return (
        Listing.objects.select_related("owner", "owner__profile")
        .prefetch_related(primary_photo_prefetch(), "amenities")
        .annotate(
            rating_avg=Avg("reviews__rating", filter=Q(reviews__status="PUBLISHED")),
            rating_count=Count("reviews", filter=Q(reviews__status="PUBLISHED"), distinct=True),
        )
    )


def visible_listing_for(user, pk):
    """Annonce publiée, ou toute annonce pour son responsable et les administrateurs."""
    qs = detail_queryset()
    if user and user.is_authenticated:
        if user.is_admin:
            return qs.get(pk=pk)
        return qs.filter(Q(publication_status=PublicationStatus.PUBLISHED) | Q(owner=user)).get(pk=pk)
    return qs.filter(publication_status=PublicationStatus.PUBLISHED).get(pk=pk)


def owner_listings(user):
    return (
        Listing.objects.filter(owner=user)
        .select_related("owner")
        .prefetch_related(primary_photo_prefetch())
        .annotate(
            visits_pending=Count("visits", filter=Q(visits__status="PENDING"), distinct=True),
            reports_open=Count("reports", filter=Q(reports__status__in=["OPEN", "IN_REVIEW"]), distinct=True),
        )
        .order_by("-created_at")
    )
