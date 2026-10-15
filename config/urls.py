from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.accounts import urls as accounts_urls
from apps.assistant import urls as assistant_urls
from apps.listings import urls as listings_urls
from apps.listings.views import AmenityListView
from apps.moderation import urls as moderation_urls
from apps.reviews import urls as reviews_urls
from apps.transactions import urls as transactions_urls
from apps.verification import urls as verification_urls


def health(request):
    return JsonResponse({"status": "ok"})


admin_api = (
    accounts_urls.admin_urlpatterns
    + listings_urls.admin_urlpatterns
    + verification_urls.admin_urlpatterns
    + transactions_urls.admin_urlpatterns
    + reviews_urls.admin_urlpatterns
    + moderation_urls.admin_urlpatterns
    + assistant_urls.admin_urlpatterns
)

api_v1 = [
    path("auth/", include(accounts_urls.urlpatterns)),
    path("listings/", include(listings_urls.urlpatterns)),
    path("amenities/", AmenityListView.as_view(), name="amenities"),
    path("search/", include("apps.search.urls")),
    path("verification/", include(verification_urls.urlpatterns)),
    path("assistant/", include(assistant_urls.urlpatterns)),
    path("visits/", include("apps.visits.urls")),
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
    # Interface d'administration Django (secours technique), séparée de l'espace /admin du frontend.
    path("django-admin/", admin.site.urls),
]

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
