import re

from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.accounts import urls as accounts_urls
from apps.applications import urls as applications_urls
from apps.assistant import urls as assistant_urls
from apps.listings import urls as listings_urls
from apps.listings.views import AmenityListView
from apps.moderation import urls as moderation_urls
from apps.reviews import urls as reviews_urls
from apps.transactions import urls as transactions_urls
from apps.verification import urls as verification_urls


def health(request):
    return JsonResponse({"status": "ok"})


def ready(request):
    """Prêt à servir : base joignable et toutes les migrations appliquées (healthcheck Railway recommandé).

    Une migration oubliée (ex. table du dossier locatif absente) fait échouer le healthcheck : Railway conserve alors
    l'ancien déploiement au lieu de servir des erreurs 500. Seul le nombre de migrations manquantes est exposé.
    """
    from django.db import DatabaseError, connection
    from django.db.migrations.executor import MigrationExecutor

    try:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except DatabaseError:
        return JsonResponse({"status": "database_unavailable"}, status=503)
    if pending:
        return JsonResponse({"status": "migrations_pending", "pending": len(pending)}, status=503)
    return JsonResponse({"status": "ready"})


admin_api = (
    accounts_urls.admin_urlpatterns
    + listings_urls.admin_urlpatterns
    + verification_urls.admin_urlpatterns
    + transactions_urls.admin_urlpatterns
    + reviews_urls.admin_urlpatterns
    + moderation_urls.admin_urlpatterns
    + assistant_urls.admin_urlpatterns
    + applications_urls.admin_urlpatterns
)

api_v1 = [
    path("auth/", include(accounts_urls.urlpatterns)),
    path("listings/", include(listings_urls.urlpatterns)),
    path("amenities/", AmenityListView.as_view(), name="amenities"),
    path("search/", include("apps.search.urls")),
    path("verification/", include(verification_urls.urlpatterns)),
    path("assistant/", include(assistant_urls.urlpatterns)),
    path("visits/", include("apps.visits.urls")),
    path("applications/", include(applications_urls.urlpatterns)),
    path("transactions/", include(transactions_urls.urlpatterns)),
    path("contracts/", include("apps.contracts.urls")),
    path("reviews/", include(reviews_urls.urlpatterns)),
    path("reports/", include(moderation_urls.urlpatterns)),
    path("notifications/", include("apps.notifications.urls")),
    path("admin/", include(admin_api)),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

urlpatterns = [
    path("api/v1/", include(api_v1)),
    path("health/", health),
    path("health/ready/", ready),
    # Interface d'administration Django (secours technique), séparée de l'espace /admin du frontend.
    path("django-admin/", admin.site.urls),
]

# Stockage local (volume Railway) : les photos publiques sont servies par Django, y compris en production.
# Avec un stockage S3, les URL pointent directement vers le bucket et cette route n'existe pas.
if settings.STORAGES["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage":
    from apps.media.views import serve_public_media

    urlpatterns += [re_path(rf"^{re.escape(settings.MEDIA_URL.lstrip('/'))}(?P<path>.+)$", serve_public_media, name="public-media")]
