"""Contrôle des justificatifs : type réel détecté par signature binaire, pas par l'extension."""

import hashlib
import re

from django.conf import settings

from apps.core_errors import BusinessError

SIGNATURES = {
    b"%PDF-": "application/pdf",
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}


def sniff(uploaded) -> tuple[str, str, int]:
    if uploaded.size > settings.MAX_DOCUMENT_SIZE_MB * 1024 * 1024:
        raise BusinessError(f"Fichier trop lourd (maximum {settings.MAX_DOCUMENT_SIZE_MB} Mo).", code="file_too_large")
    if uploaded.size == 0:
        raise BusinessError("Fichier vide.")
    uploaded.seek(0)
    head = uploaded.read(16)
    content_type = next((ct for sig, ct in SIGNATURES.items() if head.startswith(sig)), None)
    if not content_type:
        raise BusinessError("Formats acceptés : PDF, JPEG, PNG.", code="invalid_file_type")
    uploaded.seek(0)
    digest = hashlib.sha256()
    for chunk in uploaded.chunks():
        digest.update(chunk)
    uploaded.seek(0)
    return content_type, digest.hexdigest(), uploaded.size


def safe_name(name: str) -> str:
    name = re.sub(r"[^\w.\- ]+", "_", name or "document")[:100]
    return name or "document"
