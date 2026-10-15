import shutil
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Profile, Role, User
from apps.listings import services as listing_services
from apps.listings.demo_images import building, fake_pdf
from apps.visits.models import VisitSlot


@pytest.fixture(autouse=True)
def _media_cleanup():
    yield
    shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
    shutil.rmtree(settings.PRIVATE_MEDIA_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()


def make_user(role=Role.CUSTOMER, email=None, **extra):
    n = User.objects.count() + 1
    user = User.objects.create_user(
        email=email or f"{role.lower()}{n}@test.sn", password="Motdepasse-solide-1", first_name="Prénom", last_name=f"Nom{n}", **extra
    )
    user.role = role
    user.save(update_fields=["role"])
    Profile.objects.create(user=user)
    return user


@pytest.fixture
def api():
    return APIClient()


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def owner(db):
    return make_user(Role.OWNER)


@pytest.fixture
def customer(db):
    return make_user(Role.CUSTOMER)


@pytest.fixture
def admin(db):
    return make_user(Role.ADMIN, is_staff=True)


def make_listing(owner, publish=True, **overrides):
    data = dict(
        title="Appartement test", description="Description", property_type="APARTMENT", transaction_type="RENT",
        price=250000, surface_m2=80, rooms=3, bedrooms=2, bathrooms=1, city="Dakar", district="Fann Hock",
        address_private="Rue 10, Fann Hock", latitude=Decimal("14.685812"), longitude=Decimal("-17.465234"),
    )
    amenities = overrides.pop("amenities", None)
    data.update(overrides)
    listing = listing_services.create_listing(owner=owner, amenities=amenities, **data)
    if publish:
        listing_services.add_photo(actor=owner, listing=listing, uploaded=building(1))
        listing = listing_services.change_publication(actor=owner, listing=listing, target="PUBLISHED")
    return listing


@pytest.fixture
def listing(owner):
    return make_listing(owner)


def make_slot(listing, hours_ahead=48, minutes=45):
    start = timezone.now().replace(microsecond=0, second=0) + timedelta(hours=hours_ahead)
    return VisitSlot.objects.create(listing=listing, host=listing.owner, starts_at=start, ends_at=start + timedelta(minutes=minutes))


def past_slot(listing, days=2):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(timezone.localdate() - timedelta(days=days), time(10)), tz)
    return VisitSlot.objects.create(listing=listing, host=listing.owner, starts_at=start, ends_at=start + timedelta(minutes=45))


__all__ = ["make_user", "make_listing", "make_slot", "past_slot", "client_for", "building", "fake_pdf"]
