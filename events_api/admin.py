from django.contrib import admin

from events_api.models import (
    EscrowPayment,
    Event,
    EventEnrollment,
    EventFraudReport,
    EventGrievance,
    OrganizerPaymentAccount,
    PlatformTreasury,
    UserWallet,
    WalletLedgerEntry,
    WalletPayoutRequest,
    WalletTopUp,
)


@admin.register(PlatformTreasury)
class PlatformTreasuryAdmin(admin.ModelAdmin):
    list_display = ("id", "held_escrow_balance", "available_balance", "updated_at")


@admin.register(UserWallet)
class UserWalletAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "balance", "currency", "updated_at")
    search_fields = ("user__username",)
    raw_id_fields = ("user",)


@admin.register(WalletLedgerEntry)
class WalletLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "kind", "amount", "created_at")
    list_filter = ("kind",)
    search_fields = ("note",)


@admin.register(WalletTopUp)
class WalletTopUpAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "amount", "razorpay_order_id", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("razorpay_order_id", "razorpay_payment_id")


@admin.register(WalletPayoutRequest)
class WalletPayoutRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "amount", "status", "reviewed_by", "created_at")
    list_filter = ("status",)
    raw_id_fields = ("user", "reviewed_by")


@admin.register(EventGrievance)
class EventGrievanceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "event", "status", "created_at")
    list_filter = ("status",)
    raw_id_fields = ("user", "event")


@admin.register(OrganizerPaymentAccount)
class OrganizerPaymentAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "is_verified", "stripe_connected_account_id", "created_at")
    list_filter = ("is_verified",)
    search_fields = ("user__username", "stripe_connected_account_id", "razorpay_linked_account_id")


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "organizer",
        "status",
        "event_date",
        "organizer_identity_verified",
        "created_at",
    )
    list_filter = ("status", "organizer_identity_verified")
    search_fields = ("title", "venue_name", "organizer__username")
    raw_id_fields = ("organizer", "payment_account")


@admin.register(EventEnrollment)
class EventEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("public_id", "event", "user", "quantity", "checked_in_quantity", "created_at")
    search_fields = ("public_id", "user__username")
    raw_id_fields = ("event", "user")


@admin.register(EscrowPayment)
class EscrowPaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event",
        "user",
        "amount",
        "status",
        "funding_source",
        "transaction_id",
        "created_at",
    )
    list_filter = ("status", "funding_source")
    search_fields = ("transaction_id", "razorpay_order_id", "razorpay_payment_id")


@admin.register(EventFraudReport)
class EventFraudReportAdmin(admin.ModelAdmin):
    list_display = ("id", "event", "user", "created_at")
    search_fields = ("reason",)
