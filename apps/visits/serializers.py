from rest_framework import serializers

from apps.listings.serializers import ListingCardSerializer

from .models import Visit, VisitSlot, VisitStatus


class SlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisitSlot
        fields = ["id", "starts_at", "ends_at"]


class HostSlotSerializer(serializers.ModelSerializer):
    booked = serializers.SerializerMethodField()

    class Meta:
        model = VisitSlot
        fields = ["id", "listing", "starts_at", "ends_at", "is_active", "booked"]

    def get_booked(self, obj) -> bool:
        return any(v.status in ("PENDING", "CONFIRMED") for v in obj.visits.all())


class SlotBatchSerializer(serializers.Serializer):
    listing = serializers.UUIDField()
    date = serializers.DateField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    duration_minutes = serializers.IntegerField(min_value=15, max_value=240, default=30)


class BookSerializer(serializers.Serializer):
    slot_id = serializers.IntegerField()
    message = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class VisitStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[VisitStatus.CONFIRMED, VisitStatus.CANCELLED, VisitStatus.COMPLETED])
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class VisitSerializer(serializers.ModelSerializer):
    listing = ListingCardSerializer(read_only=True)
    slot = SlotSerializer(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    customer_name = serializers.CharField(source="customer.public_name", read_only=True)
    host_name = serializers.CharField(source="host.public_name", read_only=True)
    address = serializers.SerializerMethodField()
    contact_phone = serializers.SerializerMethodField()
    my_role = serializers.SerializerMethodField()

    class Meta:
        model = Visit
        fields = [
            "id", "listing", "slot", "status", "status_label", "message", "customer_name", "host_name",
            "address", "contact_phone", "my_role", "created_at", "confirmed_at", "completed_at",
            "cancelled_at", "cancel_reason",
        ]

    def _confirmed(self, obj):
        return obj.status in (VisitStatus.CONFIRMED, VisitStatus.COMPLETED)

    def get_address(self, obj) -> str | None:
        # L'adresse exacte n'est communiquée qu'après confirmation par le propriétaire ou l'agent.
        return obj.listing.address_private if self._confirmed(obj) else None

    def get_contact_phone(self, obj) -> str | None:
        if not self._confirmed(obj):
            return None
        user = self.context["request"].user
        other = obj.host if user.pk == obj.customer_id else obj.customer
        return other.phone or None

    def get_my_role(self, obj) -> str:
        user = self.context["request"].user
        return "host" if user.pk == obj.host_id else "customer"
