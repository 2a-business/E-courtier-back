"""Diffusion des photos publiques depuis le stockage local (volume Railway monté sur /app/media).

- Lecture seule (GET/HEAD) et liste blanche : seuls les sous-dossiers PUBLIC_MEDIA_PREFIXES (listings/) de
  MEDIA_ROOT sont diffusés. Les justificatifs (<volume>/private), lost+found ou tout autre fichier du volume
  répondent 404 ; ils ne sont accessibles que par DocumentFileView, après contrôle d'accès.
- Les fichiers sont transmis par blocs (FileResponse), jamais chargés entièrement en mémoire.
- Noms uniques (uuid) jamais réécrits : cache long « immutable » + revalidation If-Modified-Since.
"""

import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotModified
from django.utils._os import safe_join
from django.utils.http import http_date
from django.views.decorators.http import require_safe
from django.views.static import was_modified_since

PUBLIC_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def resolve_public_file(path: str) -> Path:
    """Chemin absolu d'un fichier public, ou Http404 (traversée, dossier non public, extension, absence)."""
    try:
        full_path = Path(safe_join(settings.MEDIA_ROOT, path)).resolve()
    except (SuspiciousFileOperation, ValueError):
        raise Http404("Fichier introuvable.")
    media_root = Path(settings.MEDIA_ROOT).resolve()
    public_dirs = [media_root / prefix for prefix in settings.PUBLIC_MEDIA_PREFIXES]
    if not any(full_path.is_relative_to(d) for d in public_dirs):
        raise Http404("Fichier introuvable.")
    if full_path.suffix.lower() not in PUBLIC_EXTENSIONS or not full_path.is_file():
        raise Http404("Fichier introuvable.")
    return full_path


@require_safe
def serve_public_media(request, path: str):
    full_path = resolve_public_file(path)
    stat = full_path.stat()
    if not was_modified_since(request.META.get("HTTP_IF_MODIFIED_SINCE"), stat.st_mtime):
        return HttpResponseNotModified()
    content_type = mimetypes.guess_type(full_path.name)[0] or "application/octet-stream"
    if request.method == "HEAD":
        # Pas de corps pour HEAD (gunicorn le supprimerait en journalisant un avertissement).
        response = HttpResponse(content_type=content_type)
        response["Content-Length"] = str(stat.st_size)
    else:
        response = FileResponse(full_path.open("rb"), content_type=content_type)
    response["Last-Modified"] = http_date(stat.st_mtime)
    response["Cache-Control"] = f"public, max-age={settings.MEDIA_CACHE_SECONDS}, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    # Le frontend est servi depuis une autre origine : autoriser explicitement l'intégration des images.
    response["Cross-Origin-Resource-Policy"] = "cross-origin"
    return response
