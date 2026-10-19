"""Contrôles de déploiement du stockage des fichiers (``manage.py check --deploy``).

Avertissements et non erreurs : le build Railway s'exécute sans volume monté (les volumes ne sont
disponibles qu'à l'exécution), ces contrôles ne doivent donc pas faire échouer la construction.
"""

from pathlib import Path

from django.conf import settings
from django.core.checks import Tags, Warning, register


def _is_within(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


@register(Tags.files, deploy=True)
def check_media_storage(app_configs=None, **kwargs):
    if settings.STORAGES["default"]["BACKEND"] != "django.core.files.storage.FileSystemStorage":
        return []
    media_root = Path(settings.MEDIA_ROOT).resolve()
    private_root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
    base_dir = Path(settings.BASE_DIR).resolve()
    volume = settings.VOLUME_ROOT
    warnings = []
    if volume is None and (_is_within(media_root, base_dir) or _is_within(private_root, base_dir)):
        warnings.append(Warning(
            "Les fichiers téléversés sont écrits dans le répertoire de l'application, sans volume persistant : "
            "ils seront perdus au prochain redéploiement.",
            hint="Attachez un volume Railway au service (montage /app/media) ou définissez MEDIA_ROOT et "
                 "PRIVATE_MEDIA_ROOT sur un disque persistant.",
            id="media.W001",
        ))
    if volume is not None:
        root = Path(volume).resolve()
        for name, path in (("MEDIA_ROOT", media_root), ("PRIVATE_MEDIA_ROOT", private_root)):
            if not _is_within(path, root):
                warnings.append(Warning(
                    f"{name} ({path}) est en dehors du volume monté ({root}) : ces fichiers ne seront pas conservés.",
                    hint=f"Supprimez la variable {name} pour utiliser l'emplacement par défaut sur le volume.",
                    id="media.W002",
                ))
    return warnings
