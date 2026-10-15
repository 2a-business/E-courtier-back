from django.contrib import admin

from .models import Amenity, Listing, ListingPhoto


class PhotoInline(admin.TabularInline):
    model = ListingPhoto
    extra = 0


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ["title", "owner", "transaction_type", "price", "district", "publication_status", "verification_status"]
    list_filter = ["publication_status", "verification_status", "transaction_type", "property_type"]
    search_fields = ["title", "district", "city"]
    readonly_fields = ["verification_status", "is_demo"]
    inlines = [PhotoInline]


admin.site.register(Amenity)
