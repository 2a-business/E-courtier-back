"""Suppression des fichiers physiques alignée sur la transaction en cours."""

from django.db import transaction


def delete_after_commit(*fields) -> None:
    """Supprime les fichiers seulement si la transaction aboutit : un rollback ne laisse jamais
    une ligne en base pointant vers un fichier déjà effacé."""
    targets = [(field.storage, field.name) for field in fields if field and field.name]

    def _delete():
        for storage, name in targets:
            storage.delete(name)

    transaction.on_commit(_delete)
