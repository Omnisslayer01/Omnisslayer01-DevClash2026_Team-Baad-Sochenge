from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from events_api import services
from events_api import wallet_services
from events_api.models import (
    Event,
    EventEnrollment,
    EventFraudReport,
    EventGrievance,
    OrganizerPaymentAccount,
    WalletPayoutRequest,
    WalletTopUp,
)


def _validate_image_upload(image, *, max_mb: int = 5) -> None:
    allowed = {"image/jpeg", "image/png", "image/webp"}
    ct = (getattr(image, "content_type", None) or "").lower()
    if ct and ct not in allowed:
        raise serializers.ValidationError("Banner must be JPEG, PNG, or WebP.")
    if image.size > max_mb * 1024 * 1024:
        raise serializers.ValidationError(f"Banner must be under {max_mb} MB.")


def _validate_payment_account(account: OrganizerPaymentAccount, user) -> OrganizerPaymentAccount:
    if account.user_id != user.id:
        raise serializers.ValidationError(
            {"payment_account": "Payment account does not belong to this organizer."}
        )
    if not account.is_verified:
        raise serializers.ValidationError(
            {"payment_account": "Payment account must be ops-verified before hosting."}
        )
    if not (
        (account.stripe_connected_account_id or "").strip()
        or (account.razorpay_linked_account_id or "").strip()
    ):
        raise serializers.ValidationError(
            {"payment_account": "Provide a Stripe connected account id or Razorpay linked account id."}
        )
    sid = (account.stripe_connected_account_id or "").strip()
    if sid and not sid.startswith("acct_"):
        raise serializers.ValidationError(
            {"stripe_connected_account_id": "Stripe connected accounts typically start with acct_."}
        )
    return account


class OrganizerPaymentAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizerPaymentAccount
        fields = (
            "id",
            "stripe_connected_account_id",
            "razorpay_linked_account_id",
            "is_verified",
            "created_at",
        )
        read_only_fields = ("id", "is_verified", "created_at")


class EventListSerializer(serializers.ModelSerializer):
    total_registered = serializers.SerializerMethodField()
    total_checked_in = serializers.SerializerMethodField()
    is_verified = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = (
            "id",
            "organizer",
            "title",
            "description",
            "venue_name",
            "address",
            "latitude",
            "longitude",
            "formatted_address",
            "banner_image",
            "ticket_price",
            "total_slots",
            "event_date",
            "event_time",
            "organizer_identity_verified",
            "is_verified",
            "status",
            "payment_account",
            "total_registered",
            "total_checked_in",
            "created_at",
        )
        read_only_fields = (
            "id",
            "organizer",
            "title",
            "description",
            "venue_name",
            "address",
            "latitude",
            "longitude",
            "formatted_address",
            "banner_image",
            "ticket_price",
            "total_slots",
            "event_date",
            "event_time",
            "organizer_identity_verified",
            "is_verified",
            "status",
            "payment_account",
            "total_registered",
            "total_checked_in",
            "created_at",
        )

    def get_total_registered(self, obj):
        return obj.total_registered

    def get_total_checked_in(self, obj):
        return obj.total_checked_in

    def get_is_verified(self, obj):
        return obj.is_verified


class EventCreateSerializer(serializers.ModelSerializer):
    """Create with address geocoding / dev coordinates + mandatory banner + payment account."""

    latitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True, write_only=True
    )
    longitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True, write_only=True
    )

    class Meta:
        model = Event
        fields = (
            "title",
            "description",
            "venue_name",
            "address",
            "latitude",
            "longitude",
            "banner_image",
            "ticket_price",
            "total_slots",
            "event_date",
            "event_time",
            "payment_account",
        )

    def validate_banner_image(self, value):
        _validate_image_upload(value)
        return value

    def validate(self, attrs):
        resolved = services.resolve_venue(
            address=attrs["address"],
            venue_name=attrs.get("venue_name", ""),
            latitude=attrs.pop("latitude", None),
            longitude=attrs.pop("longitude", None),
        )
        attrs["latitude"] = resolved["latitude"]
        attrs["longitude"] = resolved["longitude"]
        attrs["formatted_address"] = resolved["formatted_address"]
        return attrs

    def validate_payment_account(self, value):
        return _validate_payment_account(value, self.context["request"].user)

    def create(self, validated_data):
        user = self.context["request"].user
        if not services.organizer_identity_allowed_for_events(user):
            raise PermissionDenied(
                "Verified identity (blue/green badge or id_verified) required to create events."
            )
        validated_data["organizer"] = user
        validated_data["organizer_identity_verified"] = True
        return super().create(validated_data)


class EventEnrollmentSerializer(serializers.ModelSerializer):
    qr_png_base64 = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = EventEnrollment
        fields = (
            "id",
            "public_id",
            "attendance_key",
            "event",
            "user",
            "quantity",
            "checked_in_quantity",
            "checked_in_at",
            "qr_png_base64",
            "created_at",
        )
        read_only_fields = (
            "id",
            "public_id",
            "attendance_key",
            "event",
            "user",
            "checked_in_quantity",
            "checked_in_at",
            "qr_png_base64",
            "created_at",
        )

    def get_qr_png_base64(self, obj):
        payload = f"{obj.public_id}|{obj.attendance_key}"
        return services.generate_qr_png_base64_from_string(payload)


class EnrollSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1, default=1)


class ScanQrSerializer(serializers.Serializer):
    public_id = serializers.UUIDField(required=False, allow_null=True)
    qr_payload = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=True
    )

    def validate(self, attrs):
        qp = (attrs.get("qr_payload") or "").strip()
        pid = attrs.get("public_id")
        if qp and pid is not None:
            raise serializers.ValidationError(
                "Send only one of public_id or qr_payload."
            )
        if not qp and pid is None:
            raise serializers.ValidationError("Provide public_id or qr_payload.")
        return attrs


class FraudReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventFraudReport
        fields = ("id", "reason", "created_at")
        read_only_fields = ("id", "created_at")


def enroll_user_in_event(*, event: Event, user, quantity: int) -> dict:
    if quantity < 1:
        raise serializers.ValidationError({"quantity": "Invalid quantity."})

    with transaction.atomic():
        locked = Event.objects.select_for_update().get(pk=event.pk)
        if locked.status != Event.STATUS_ACTIVE:
            raise serializers.ValidationError(
                {"detail": "Event is not accepting enrollments."}
            )
        used = (
            EventEnrollment.objects.filter(event=locked).aggregate(s=Sum("quantity"))["s"]
            or 0
        )
        if used + quantity > locked.total_slots:
            raise serializers.ValidationError({"quantity": "Not enough slots remaining."})
        en, created = EventEnrollment.objects.select_for_update().get_or_create(
            event=locked,
            user=user,
            defaults={"quantity": quantity},
        )
        if not created:
            raise serializers.ValidationError(
                {"detail": "Already enrolled. Cancel and re-book is not implemented."}
            )
        amount = (locked.ticket_price or Decimal("0")) * Decimal(quantity)
        if amount > 0:
            wallet_services.get_or_create_user_wallet(user)
            pay = services.charge_and_hold_escrow(
                user=user, event=locked, enrollment=en, amount=amount
            )
        else:
            pay = None
    data = EventEnrollmentSerializer(en, context={"request": None}).data
    if pay:
        data["escrow_transaction_id"] = pay.transaction_id
        data["escrow_status"] = pay.status
    return data


class RazorpayTopUpOrderSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("1")
    )


class RazorpayTopUpVerifySerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField(max_length=64)
    razorpay_payment_id = serializers.CharField(max_length=64)
    razorpay_signature = serializers.CharField(max_length=256)


class WalletPayoutBodySerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("1")
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")


class EventGrievanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventGrievance
        fields = ("id", "event", "description", "status", "created_at")
        read_only_fields = ("id", "status", "created_at")


class WalletPayoutRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletPayoutRequest
        fields = (
            "id",
            "user",
            "amount",
            "status",
            "note",
            "reviewed_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "user",
            "amount",
            "status",
            "note",
            "reviewed_by",
            "created_at",
            "updated_at",
        )
