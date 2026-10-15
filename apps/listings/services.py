"""Opérations métier sur les annonces. Aucune dépendance à la requête HTTP."""

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core_errors import BusinessError, Forbidden, InvalidTransition
from apps.moderation.services import log_action

from . import images
from .models import Amenity, Listing, ListingPhoto, PublicationStatus, VerificationStatus

# Champs dont la modification invalide une vérification déjà accordée (le bien n'est plus le même).
VERIFICATION_SENSITIVE_FIELDS = {"property_type", "transaction_type", "city", "district", "address_private", "owner"}


def can_manage(user, listing: Listing) -> bool:
    return bool(user and user.is_authenticated and (user.is_admin or listing.owner_id == user.pk))


def ensure_can_manage(user, listing: Listing) -> None:
    if not can_manage(user, listing):
        raise Forbidden("Vous ne gérez pas cette annonce.")


def _set_amenities(listing: Listing, slugs):
    if slugs is None:
        return
    found = list(Amenity.objects.filter(slug__in=slugs))
    unknown = set(slugs) - {a.slug for a in found}
    if unknown:
        raise BusinessError(f"Équipements inconnus : {', '.join(sorted(unknown))}.")
    listing.amenities.set(found)


@transaction.atomic
def create_listing(*, owner, amenities=None, **data) -> Listing:
    if not owner.can_manage_listings:
        raise Forbidden("Seuls les propriétaires et agents peuvent publier des annonces.")
    listing = Listing(owner=owner, **data)
    listing.full_clean()
    listing.save()
    _set_amenities(listing, amenities)
    log_action(actor=owner, action="listing.created", target=listing)
    return listing


@transaction.atomic
def update_listing(*, actor, listing: Listing, amenities=None, **data) -> Listing:
    ensure_can_manage(actor, listing)
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    if listing.publication_status == PublicationStatus.SUSPENDED and not actor.is_admin:
        raise Forbidden("Cette annonce est suspendue par la modération.")
    changed_sensitive = any(
        field in VERIFICATION_SENSITIVE_FIELDS and getattr(listing, field) != value for field, value in data.items()
    )
    for field, value in data.items():
        setattr(listing, field, value)
    listing.full_clean()
    if changed_sensitive and listing.verification_status in (VerificationStatus.APPROVED, VerificationStatus.PENDING):
        from apps.verification.services import invalidate_verification

        listing.save()
        invalidate_verification(listing=listing, reason="Informations essentielles modifiées")
        listing.refresh_from_db()
    else:
        listing.save()
    _set_amenities(listing, amenities)
    return listing


@transaction.atomic
def change_publication(*, actor, listing: Listing, target: str) -> Listing:
    """Transitions publiables par le responsable : DRAFT ⇄ PUBLISHED, → ARCHIVED."""
    ensure_can_manage(actor, listing)
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    current = listing.publication_status
    allowed = {
        PublicationStatus.DRAFT: {PublicationStatus.PUBLISHED, PublicationStatus.ARCHIVED},
        PublicationStatus.PUBLISHED: {PublicationStatus.DRAFT, PublicationStatus.ARCHIVED},
        PublicationStatus.ARCHIVED: {PublicationStatus.DRAFT},
        PublicationStatus.SUSPENDED: set(),
    }
    if target not in allowed[PublicationStatus(current)]:
        if current == PublicationStatus.SUSPENDED:
            raise InvalidTransition("Annonce suspendue : seule la modération peut la rétablir.")
        raise InvalidTransition(f"Passage de « {listing.get_publication_status_display()} » à {target} impossible.")
    if target == PublicationStatus.PUBLISHED and not listing.photos.exists():
        raise BusinessError("Ajoutez au moins une photo avant de publier.", code="photo_required")
    listing.publication_status = target
    if target == PublicationStatus.PUBLISHED and not listing.published_at:
        listing.published_at = timezone.now()
    listing.save(update_fields=["publication_status", "published_at", "updated_at"])
    log_action(actor=actor, action=f"listing.{target.lower()}", target=listing)
    return listing


@transaction.atomic
def moderate_listing(*, actor, listing: Listing, action: str, reason: str) -> Listing:
    if not actor.is_admin:
        raise Forbidden("Action réservée aux administrateurs.")
    if not reason.strip():
        raise BusinessError("Un motif est obligatoire.")
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    if action == "suspend":
        if listing.publication_status == PublicationStatus.SUSPENDED:
            raise InvalidTransition("Annonce déjà suspendue.")
        listing.publication_status = PublicationStatus.SUSPENDED
        listing.is_featured = False
    elif action == "restore":
        if listing.publication_status != PublicationStatus.SUSPENDED:
            raise InvalidTransition("L'annonce n'est pas suspendue.")
        listing.publication_status = PublicationStatus.DRAFT
    else:
        raise BusinessError("Action de modération inconnue.")
    listing.save(update_fields=["publication_status", "is_featured", "updated_at"])
    log_action(actor=actor, action=f"listing.{action}", target=listing, metadata={"reason": reason[:300]})

    from apps.notifications.services import notify

    notify(
        listing.owner,
        kind=f"listing.{action}",
        title="Annonce suspendue" if action == "suspend" else "Annonce rétablie (brouillon)",
        body=f"« {listing.title} » — motif : {reason[:300]}",
        link="/tableau-de-bord",
    )
    return listing


@transaction.atomic
def set_featured(*, actor, listing: Listing, featured: bool) -> Listing:
    if not actor.is_admin:
        raise Forbidden("Action réservée aux administrateurs.")
    if featured and not listing.is_public:
        raise BusinessError("Seule une annonce publiée peut être mise à la une.")
    listing.is_featured = featured
    listing.save(update_fields=["is_featured", "updated_at"])
    log_action(actor=actor, action="listing.featured" if featured else "listing.unfeatured", target=listing)
    return listing


@transaction.atomic
def add_photo(*, actor, listing: Listing, uploaded, caption: str = "") -> ListingPhoto:
    ensure_can_manage(actor, listing)
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    count = listing.photos.count()
    if count >= settings.MAX_PHOTOS_PER_LISTING:
        raise BusinessError(f"Maximum {settings.MAX_PHOTOS_PER_LISTING} photos par annonce.")
    full, thumb = images.process_upload(uploaded)
    position = (listing.photos.aggregate(m=Max("position"))["m"] or 0) + 1
    photo = ListingPhoto(listing=listing, caption=caption[:80], position=position, is_primary=count == 0)
    photo.image.save("photo.jpg", full, save=False)
    photo.thumbnail.save("thumb.jpg", thumb, save=False)
    photo.save()
    return photo


@transaction.atomic
def set_primary_photo(*, actor, photo: ListingPhoto) -> ListingPhoto:
    ensure_can_manage(actor, photo.listing)
    ListingPhoto.objects.filter(listing=photo.listing, is_primary=True).update(is_primary=False)
    photo.is_primary = True
    photo.save(update_fields=["is_primary"])
    return photo


@transaction.atomic
def reorder_photos(*, actor, listing: Listing, ordered_ids: list[int]) -> None:
    ensure_can_manage(actor, listing)
    photos = {p.pk: p for p in listing.photos.all()}
    if set(ordered_ids) != set(photos):
        raise BusinessError("La liste doit contenir toutes les photos de l'annonce.")
    for index, pk in enumerate(ordered_ids):
        photos[pk].position = index
    ListingPhoto.objects.bulk_update(photos.values(), ["position"])


@transaction.atomic
def delete_photo(*, actor, photo: ListingPhoto) -> None:
    listing = photo.listing
    ensure_can_manage(actor, listing)
    was_primary = photo.is_primary
    photo.image.delete(save=False)
    photo.thumbnail.delete(save=False)
    photo.delete()
    if was_primary:
        nxt = listing.photos.order_by("position").first()
        if nxt:
            nxt.is_primary = True
            nxt.save(update_fields=["is_primary"])
        elif listing.publication_status == PublicationStatus.PUBLISHED:
            listing.publication_status = PublicationStatus.DRAFT
            listing.save(update_fields=["publication_status", "updated_at"])


@transaction.atomic
def delete_listing(*, actor, listing: Listing) -> None:
    ensure_can_manage(actor, listing)
    if listing.publication_status != PublicationStatus.DRAFT or listing.visits.exists() or listing.transactions.exists():
        raise BusinessError(
            "Seul un brouillon sans visite ni dossier peut être supprimé. Archivez plutôt l'annonce.", code="cannot_delete"
        )
    for photo in listing.photos.all():
        photo.image.delete(save=False)
        photo.thumbnail.delete(save=False)
    log_action(actor=actor, action="listing.deleted", target=listing, metadata={"title": listing.title[:80]})
    listing.delete()
