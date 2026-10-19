"""Diffusion des photos publiques, isolement des justificatifs, suppressions et contrôles de stockage."""

from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import override_settings

from apps.listings import services as listing_services
from apps.listings.models import ListingPhoto
from apps.media.checks import check_media_storage
from apps.verification.models import VerificationDocument
from conftest import building, client_for, fake_pdf, make_user

pytestmark = pytest.mark.django_db


def media_path(url: str) -> str:
    return url[url.index("/media/"):]


def upload_document(listing):
    res = client_for(listing.owner).post(
        f"/api/v1/verification/listings/{listing.pk}/documents/", {"doc_type": "ID_CARD", "file": fake_pdf("cni")}, format="multipart"
    )
    assert res.status_code == 201, res.data
    return VerificationDocument.objects.get(pk=res.data["id"])


def test_listing_photos_are_served_with_long_cache(api, listing):
    detail = api.get(f"/api/v1/listings/{listing.pk}/").data
    photo = ListingPhoto.objects.get(listing=listing)
    for url, field in ((detail["photos"][0]["image"], photo.image), (detail["photos"][0]["thumbnail"], photo.thumbnail)):
        res = api.get(media_path(url))
        assert res.status_code == 200
        assert res.streaming, "le fichier doit être transmis par blocs, pas chargé en mémoire"
        assert res["Content-Type"] == "image/jpeg"
        assert "immutable" in res["Cache-Control"] and f"max-age={settings.MEDIA_CACHE_SECONDS}" in res["Cache-Control"]
        assert res["X-Content-Type-Options"] == "nosniff"
        with field.open("rb") as f:
            assert b"".join(res.streaming_content) == f.read()
    assert detail["cover"] and api.get(media_path(detail["cover"])).status_code == 200


def test_head_and_conditional_requests(api, listing):
    url = f"{settings.MEDIA_URL}{ListingPhoto.objects.get(listing=listing).image.name}"
    head = api.head(url)
    assert head.status_code == 200 and head["Last-Modified"] and head.content == b""
    assert int(head["Content-Length"]) == ListingPhoto.objects.get(listing=listing).image.size
    assert api.get(url, HTTP_IF_MODIFIED_SINCE=head["Last-Modified"]).status_code == 304
    assert api.post(url).status_code == 405


@pytest.mark.parametrize(
    "path",
    ["/media/../config/settings/base.py", "/media/%2e%2e/manage.py", "/media/listings/inexistant.jpg", "/media//etc/passwd"],
)
def test_traversal_and_missing_files_return_404(api, listing, path):
    assert api.get(path).status_code == 404


def test_upload_is_written_under_media_root_and_url_maps_to_it(listing):
    photo = ListingPhoto.objects.get(listing=listing)
    for field in (photo.image, photo.thumbnail):
        assert field.name.startswith(f"listings/{listing.pk}/") and field.name.endswith(".jpg")
        on_disk = Path(settings.MEDIA_ROOT) / field.name
        assert on_disk.is_file() and on_disk.stat().st_size == field.size
        assert field.url == f"{settings.MEDIA_URL}{field.name}"
    assert photo.width > 0 and photo.height > 0


def test_existing_file_on_volume_is_served(api, listing):
    """Fichier déjà présent sur le volume (ex. téléversé avant le déploiement) : servi tel quel par son nom en base."""
    target = Path(settings.MEDIA_ROOT) / "listings" / str(listing.pk) / "deja-present.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    res = api.get(f"/media/listings/{listing.pk}/deja-present.jpg")
    assert res.status_code == 200 and b"".join(res.streaming_content) == b"\xff\xd8\xff\xe0fake-jpeg"


@pytest.mark.parametrize("relative", ["private/verification/x/cni.jpg", "lost+found/x.jpg", "racine.jpg"])
def test_only_public_subfolders_are_served(api, relative):
    """Production : justificatifs dans <volume>/private, lost+found à la racine du volume — jamais diffusés."""
    stray = Path(settings.MEDIA_ROOT) / relative
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"\xff\xd8\xff\xe0secret")
    assert api.get(f"/media/{relative}").status_code == 404
    assert api.get(f"/media/listings/../{relative}").status_code == 404


def test_only_image_files_are_public(api, listing):
    stray = Path(settings.MEDIA_ROOT) / "listings" / "notes.pdf"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"%PDF-1.4")
    assert api.get("/media/listings/notes.pdf").status_code == 404


def test_private_documents_never_reachable_through_public_media(api, listing):
    doc = upload_document(listing)
    stored = Path(settings.PRIVATE_MEDIA_ROOT) / doc.file.name
    assert stored.is_file() and not stored.resolve().is_relative_to(Path(settings.MEDIA_ROOT).resolve())
    private_dir = Path(settings.PRIVATE_MEDIA_ROOT).name
    for path in (f"/media/{doc.file.name}", f"/media/../{private_dir}/{doc.file.name}"):
        assert api.get(path).status_code == 404
    # Le seul accès passe par la vue authentifiée, sans cache.
    url = f"/api/v1/verification/documents/{doc.pk}/file/"
    assert api.get(url).status_code == 401
    assert client_for(make_user()).get(url).status_code == 403
    res = client_for(listing.owner).get(url)
    assert res.status_code == 200 and res["Cache-Control"] == "no-store, private"


def test_photo_files_deleted_only_after_commit(listing, django_capture_on_commit_callbacks):
    extra = listing_services.add_photo(actor=listing.owner, listing=listing, uploaded=building(5))
    image, thumb = extra.image.name, extra.thumbnail.name
    storage = extra.image.storage
    with django_capture_on_commit_callbacks() as callbacks:
        listing_services.delete_photo(actor=listing.owner, photo=extra)
        assert storage.exists(image) and storage.exists(thumb), "aucun fichier effacé avant la validation"
    assert len(callbacks) == 1
    callbacks[0]()
    assert not storage.exists(image) and not storage.exists(thumb)


def test_document_file_deleted_after_commit(listing, django_capture_on_commit_callbacks):
    doc = upload_document(listing)
    name, storage = doc.file.name, doc.file.storage
    with django_capture_on_commit_callbacks(execute=True):
        assert client_for(listing.owner).delete(f"/api/v1/verification/documents/{doc.pk}/").status_code == 204
    assert not storage.exists(name)


def test_media_integrity_reports_missing_files(listing, capsys):
    call_command("media_integrity")
    assert "Tous les fichiers référencés sont présents" in capsys.readouterr().out
    photo = ListingPhoto.objects.get(listing=listing)
    photo.thumbnail.storage.delete(photo.thumbnail.name)
    with pytest.raises(CommandError, match="1 élément"):
        call_command("media_integrity", "--details")
    assert f"photo {photo.pk}" in capsys.readouterr().out


def test_storage_check_warns_without_volume(tmp_path):
    with override_settings(VOLUME_ROOT=None, MEDIA_ROOT=settings.BASE_DIR / "media", PRIVATE_MEDIA_ROOT=settings.BASE_DIR / "private_media"):
        assert [w.id for w in check_media_storage()] == ["media.W001"]
    volume = tmp_path / "storage"
    with override_settings(VOLUME_ROOT=str(volume), MEDIA_ROOT=volume / "media", PRIVATE_MEDIA_ROOT=volume / "private"):
        assert check_media_storage() == []
    with override_settings(VOLUME_ROOT=str(volume), MEDIA_ROOT=tmp_path / "ailleurs", PRIVATE_MEDIA_ROOT=volume / "private"):
        assert [w.id for w in check_media_storage()] == ["media.W002"]
