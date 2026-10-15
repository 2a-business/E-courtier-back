from django.db import IntegrityError, transaction

from apps.core_errors import BusinessError, Conflict, Forbidden
from apps.moderation.services import log_action
from apps.visits.models import Visit, VisitStatus

from .models import Review, ReviewStatus


def can_review(user, listing) -> bool:
    """Seul un client ayant effectivement visité le logement peut laisser un avis."""
    if not (user and user.is_authenticated) or listing.owner_id == user.pk:
        return False
    return Visit.objects.filter(listing=listing, customer=user, status=VisitStatus.COMPLETED).exists()


def create_review(*, author, listing, rating: int, owner_rating: int, comment: str = "") -> Review:
    if listing.owner_id == author.pk:
        raise Forbidden("Vous ne pouvez pas évaluer votre propre annonce.")
    if not can_review(author, listing):
        raise BusinessError("Un avis n'est possible qu'après une visite effectuée.", code="visit_required")
    try:
        with transaction.atomic():
            return Review.objects.create(listing=listing, author=author, rating=rating, owner_rating=owner_rating, comment=comment)
    except IntegrityError:
        raise Conflict("Vous avez déjà donné votre avis sur ce logement.", code="already_reviewed")


@transaction.atomic
def moderate_review(*, actor, review: Review, hide: bool, note: str) -> Review:
    if not actor.is_admin:
        raise Forbidden("Action réservée aux administrateurs.")
    review.status = ReviewStatus.HIDDEN if hide else ReviewStatus.PUBLISHED
    review.moderation_note = note[:300]
    review.save(update_fields=["status", "moderation_note"])
    log_action(actor=actor, action="review.hidden" if hide else "review.restored", target=review, metadata={"note": note[:200]})
    return review
