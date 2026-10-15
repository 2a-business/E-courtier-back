"""Validation et réencodage des images : seules des images JPEG/PNG/WEBP réelles sont acceptées.

Le réencodage en JPEG supprime les métadonnées EXIF (dont la géolocalisation) et réduit le poids.
"""

from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.core_errors import BusinessError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_DIMENSION = 1600
THUMB_DIMENSION = 480
Image.MAX_IMAGE_PIXELS = 40_000_000  # protection contre les « bombes de décompression »


def process_upload(uploaded) -> tuple[ContentFile, ContentFile]:
    if uploaded.size > settings.MAX_PHOTO_SIZE_MB * 1024 * 1024:
        raise BusinessError(f"Image trop lourde (maximum {settings.MAX_PHOTO_SIZE_MB} Mo).", code="file_too_large")
    try:
        image = Image.open(uploaded)
        image.verify()
        uploaded.seek(0)
        image = Image.open(uploaded)
        fmt = image.format
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise BusinessError("Le fichier n'est pas une image valide.", code="invalid_image")
    if fmt not in ALLOWED_FORMATS:
        raise BusinessError("Formats acceptés : JPEG, PNG, WEBP.", code="invalid_image")

    image = ImageOps.exif_transpose(image).convert("RGB")
    return _encode(image, MAX_DIMENSION, 82), _encode(image, THUMB_DIMENSION, 75)


def _encode(image: Image.Image, max_dim: int, quality: int) -> ContentFile:
    copy = image.copy()
    copy.thumbnail((max_dim, max_dim))
    buffer = BytesIO()
    copy.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
    return ContentFile(buffer.getvalue(), name="photo.jpg")
