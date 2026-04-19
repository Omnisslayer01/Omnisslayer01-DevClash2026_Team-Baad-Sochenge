from __future__ import annotations

import secrets
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum


class OrganizerPaymentAccount(models.Model):
    """Stripe/Razorpay-style connected account reference (verified by ops/admin)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organizer_payment_accounts",
    )
    stripe_connected_account_id = models.CharField(max_length=64, blank=True)
    razorpay_linked_account_id = models.CharField(max_length=64, blank=True)
    is_verified = models.BooleanField(
        default=False,
        help_text="Ops verified that payouts can be sent to this account.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user_id} payment account {self.pk}"


class Event(models.Model):
    STATUS_ACTIVE = "ACTIVE"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FLAGGED = "FLAGGED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FLAGGED, "Flagged"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="platform_events",
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    venue_name = models.CharField(max_length=255)
    address = models.TextField()
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    formatted_address = models.TextField(blank=True)
    banner_image = models.ImageField(upload_to="platform_events/banners/")
    ticket_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total_slots = models.PositiveIntegerField()
    event_date = models.DateField()
    event_time = models.TimeField()
    organizer_identity_verified = models.BooleanField(
        default=False,
        help_text="Snapshot: organizer satisfied blue/green badge or id_verified at publish time.",
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True,
    )
    payment_account = models.ForeignKey(
        OrganizerPaymentAccount,
        on_delete=models.PROTECT,
        related_name="events",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-event_date", "-event_time", "-created_at"]

    def __str__(self) -> str:
        return self.title

    @property
    def is_verified(self) -> bool:
        """Public-facing: organizer was verified for hosting when the event was created."""
        return self.organizer_identity_verified

    @property
    def total_registered(self) -> int:
        return self.enrollments.aggregate(total=Sum("quantity")).get("total") or 0

    @property
    def total_checked_in(self) -> int:
        return (
            self.enrollments.aggregate(total=Sum("checked_in_quantity")).get("total")
            or 0
        )


class EventEnrollment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    attendance_key = models.CharField(
        max_length=48,
        blank=True,
        db_index=True,
        help_text="Secret printed with ticket; embedded in QR for stronger check-in.",
    )
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="enrollments"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="event_enrollments",
    )
    quantity = models.PositiveIntegerField(default=1)
    checked_in_quantity = models.PositiveIntegerField(default=0)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["event", "user"], name="unique_enrollment_per_user_event"),
        ]

    def save(self, *args, **kwargs):
        if not self.attendance_key:
            self.attendance_key = secrets.token_urlsafe(24).replace("-", "x")[:40]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.user_id} → {self.event_id}"


class EscrowPayment(models.Model):
    STATUS_HELD = "HELD"
    STATUS_RELEASED = "RELEASED"
    STATUS_REFUNDED = "REFUNDED"
    STATUS_FROZEN = "FROZEN"
    STATUS_CHOICES = [
        (STATUS_HELD, "Held"),
        (STATUS_RELEASED, "Released"),
        (STATUS_REFUNDED, "Refunded"),
        (STATUS_FROZEN, "Frozen"),
    ]
    FUNDING_WALLET = "WALLET"
    FUNDING_RAZORPAY = "RAZORPAY"
    FUNDING_CHOICES = [
        (FUNDING_WALLET, "Wallet"),
        (FUNDING_RAZORPAY, "Razorpay (direct)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="escrow_payments",
    )
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="escrow_payments"
    )
    enrollment = models.OneToOneField(
        EventEnrollment,
        on_delete=models.CASCADE,
        related_name="escrow_payment",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default="INR")
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_HELD, db_index=True
    )
    transaction_id = models.CharField(max_length=128, blank=True)
    funding_source = models.CharField(
        max_length=16,
        choices=FUNDING_CHOICES,
        default=FUNDING_WALLET,
    )
    razorpay_order_id = models.CharField(max_length=64, blank=True)
    razorpay_payment_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class PlatformTreasury(models.Model):
    """Singleton (pk=1): organisation pool holding event escrow until release/refund."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    held_escrow_balance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Funds locked for active platform events.",
    )
    available_balance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Optional platform fee / surplus (not auto-used in demo).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Platform treasury"


class UserWallet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="platform_wallet",
    )
    balance = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0"))
    currency = models.CharField(max_length=8, default="INR")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.user_id} wallet ₹{self.balance}"


class WalletLedgerEntry(models.Model):
    KIND_TOP_UP = "TOP_UP"
    KIND_BOOKING_DEBIT = "BOOKING_DEBIT"
    KIND_ESCROW_IN = "ESCROW_IN"
    KIND_ESCROW_OUT_ORGANIZER = "ESCROW_OUT_ORG"
    KIND_ESCROW_OUT_REFUND = "ESCROW_OUT_REFUND"
    KIND_ESCROW_RELEASE_ORGANIZER = "ESCROW_RELEASE_ORG"
    KIND_REFUND_ATTENDEE = "REFUND_ATTENDEE"
    KIND_PAYOUT_REQUEST = "PAYOUT_REQUEST"
    KIND_PAYOUT_COMPLETED = "PAYOUT_DONE"
    KIND_PAYOUT_REJECTED = "PAYOUT_REJECT"
    KIND_GRIEVANCE_REFUND = "GRIEVANCE_REFUND"
    KIND_CHOICES = [
        (KIND_TOP_UP, "Top up"),
        (KIND_BOOKING_DEBIT, "Booking debit"),
        (KIND_ESCROW_IN, "Escrow in (treasury)"),
        (KIND_ESCROW_OUT_ORGANIZER, "Escrow out to organizer"),
        (KIND_ESCROW_OUT_REFUND, "Escrow out refund"),
        (KIND_ESCROW_RELEASE_ORGANIZER, "Escrow release organizer wallet"),
        (KIND_REFUND_ATTENDEE, "Refund attendee wallet"),
        (KIND_PAYOUT_REQUEST, "Payout request"),
        (KIND_PAYOUT_COMPLETED, "Payout completed"),
        (KIND_PAYOUT_REJECTED, "Payout rejected"),
        (KIND_GRIEVANCE_REFUND, "Grievance refund"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="wallet_ledger_entries",
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, db_index=True)
    escrow_payment = models.ForeignKey(
        EscrowPayment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    enrollment = models.ForeignKey(
        EventEnrollment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    payout_request = models.ForeignKey(
        "WalletPayoutRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    note = models.CharField(max_length=512, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class WalletTopUp(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet_topups",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    razorpay_order_id = models.CharField(max_length=64, unique=True)
    razorpay_payment_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class WalletPayoutRequest(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_PROCESSED = "PROCESSED"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_PROCESSED, "Processed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet_payout_requests",
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    note = models.CharField(max_length=500, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payout_reviews",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class EventGrievance(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED_REFUND = "APPROVED_REFUND"
    STATUS_REJECTED = "REJECTED"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED_REFUND, "Approved — refund to wallet"),
        (STATUS_REJECTED, "Rejected"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="event_grievances",
    )
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="grievances"
    )
    description = models.TextField()
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "event"],
                name="unique_grievance_per_user_event",
            ),
        ]


class EventFraudReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="event_fraud_reports",
    )
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="fraud_reports"
    )
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "event"], name="unique_fraud_report_per_user_event"
            ),
        ]
