"""
User + platform treasury wallets, escrow movements, grievance refunds, organizer payouts.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from rest_framework.exceptions import ValidationError

from events_api.models import (
    EscrowPayment,
    Event,
    EventEnrollment,
    EventGrievance,
    PlatformTreasury,
    UserWallet,
    WalletLedgerEntry,
    WalletPayoutRequest,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

User = get_user_model()


def user_may_use_wallet(user: AbstractUser) -> bool:
    from events_api.services import organizer_identity_allowed_for_events

    return organizer_identity_allowed_for_events(user)


def get_or_create_user_wallet(user: AbstractUser) -> UserWallet:
    if not user_may_use_wallet(user):
        raise ValidationError(
            {
                "detail": "Wallet is available after identity verification "
                "(verified user / blue or green trust / government ID verified).",
            }
        )
    w, _ = UserWallet.objects.get_or_create(
        user=user,
        defaults={"currency": "INR"},
    )
    return w


def get_treasury() -> PlatformTreasury:
    t, _ = PlatformTreasury.objects.get_or_create(
        pk=1,
        defaults={"held_escrow_balance": Decimal("0"), "available_balance": Decimal("0")},
    )
    return t


def _q2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"))


@transaction.atomic
def book_paid_enrollment(
    *,
    user: AbstractUser,
    event: Event,
    enrollment: EventEnrollment,
    amount: Decimal,
) -> EscrowPayment:
    """Debit attendee wallet, move funds to platform escrow held pool."""
    get_treasury()
    if amount <= 0:
        raise ValidationError({"amount": "Amount must be positive."})
    amount = _q2(amount)
    uw = UserWallet.objects.select_for_update().filter(user=user).first()
    if uw is None:
        raise ValidationError(
            {
                "detail": "No wallet yet. Create one by topping up: "
                "POST /api/v1/platform-events/wallet/top-up-order/ then verify.",
            }
        )
    if uw.balance < amount:
        raise ValidationError(
            {
                "detail": f"Insufficient wallet balance. Need ₹{amount}, have ₹{uw.balance}.",
                "required_inr": str(amount),
                "balance_inr": str(uw.balance),
            }
        )
    treasury = PlatformTreasury.objects.select_for_update().get(pk=get_treasury().pk)

    UserWallet.objects.filter(pk=uw.pk).update(balance=F("balance") - amount)
    PlatformTreasury.objects.filter(pk=treasury.pk).update(
        held_escrow_balance=F("held_escrow_balance") + amount
    )

    pay = EscrowPayment.objects.create(
        user=user,
        event=event,
        enrollment=enrollment,
        amount=amount,
        currency="INR",
        status=EscrowPayment.STATUS_HELD,
        transaction_id=f"wallet:{uuid.uuid4().hex}",
        funding_source=EscrowPayment.FUNDING_WALLET,
    )
    WalletLedgerEntry.objects.create(
        user=user,
        amount=-amount,
        kind=WalletLedgerEntry.KIND_BOOKING_DEBIT,
        escrow_payment=pay,
        enrollment=enrollment,
        note="Event booking — funds moved to platform escrow",
    )
    WalletLedgerEntry.objects.create(
        user=None,
        amount=amount,
        kind=WalletLedgerEntry.KIND_ESCROW_IN,
        escrow_payment=pay,
        enrollment=enrollment,
        note="Platform escrow held",
    )
    return pay


@transaction.atomic
def release_event_escrow_to_organizer_wallet(event: Event) -> int:
    organizer = event.organizer
    ow, _ = UserWallet.objects.select_for_update().get_or_create(
        user=organizer,
        defaults={"currency": "INR"},
    )
    treasury = PlatformTreasury.objects.select_for_update().get(pk=1)

    qs = list(
        EscrowPayment.objects.select_for_update().filter(
            event=event,
            status=EscrowPayment.STATUS_HELD,
        )
    )
    if not qs:
        return 0
    total = _q2(sum(p.amount for p in qs))
    if treasury.held_escrow_balance < total:
        raise ValidationError({"detail": "Treasury held balance is lower than escrow rows."})

    for p in qs:
        p.status = EscrowPayment.STATUS_RELEASED
        p.save(update_fields=["status", "updated_at"])

    PlatformTreasury.objects.filter(pk=1).update(
        held_escrow_balance=F("held_escrow_balance") - total
    )
    UserWallet.objects.filter(pk=ow.pk).update(balance=F("balance") + total)
    WalletLedgerEntry.objects.create(
        user=organizer,
        amount=total,
        kind=WalletLedgerEntry.KIND_ESCROW_RELEASE_ORGANIZER,
        note=f"Event {event.pk} completed — escrow to organizer wallet",
    )
    WalletLedgerEntry.objects.create(
        user=None,
        amount=-total,
        kind=WalletLedgerEntry.KIND_ESCROW_OUT_ORGANIZER,
        note=f"Treasury → organizer for event {event.pk}",
    )
    return len(qs)


@transaction.atomic
def refund_escrow_rows_to_wallets(event: Event) -> int:
    treasury = PlatformTreasury.objects.select_for_update().get(pk=1)
    qs = list(
        EscrowPayment.objects.select_for_update()
        .filter(
            event=event,
            status__in=(EscrowPayment.STATUS_HELD, EscrowPayment.STATUS_FROZEN),
        )
        .select_related("user")
    )
    if not qs:
        return 0
    total_back = _q2(sum(p.amount for p in qs))
    if treasury.held_escrow_balance < total_back:
        raise ValidationError(
            {"detail": "Treasury held balance is lower than refundable escrow rows."}
        )

    by_user: dict[int, Decimal] = {}
    for p in qs:
        uid = p.user_id
        by_user[uid] = by_user.get(uid, Decimal("0")) + p.amount
        p.status = EscrowPayment.STATUS_REFUNDED
        p.save(update_fields=["status", "updated_at"])

    PlatformTreasury.objects.filter(pk=1).update(
        held_escrow_balance=F("held_escrow_balance") - total_back
    )
    for uid, amt in by_user.items():
        amt = _q2(amt)
        uw, _ = UserWallet.objects.select_for_update().get_or_create(
            user_id=uid,
            defaults={"currency": "INR"},
        )
        UserWallet.objects.filter(pk=uw.pk).update(balance=F("balance") + amt)
        WalletLedgerEntry.objects.create(
            user_id=uid,
            amount=amt,
            kind=WalletLedgerEntry.KIND_REFUND_ATTENDEE,
            note=f"Refund to wallet for event {event.pk}",
        )
    WalletLedgerEntry.objects.create(
        user=None,
        amount=-total_back,
        kind=WalletLedgerEntry.KIND_ESCROW_OUT_REFUND,
        note=f"Treasury refunds event {event.pk}",
    )
    return len(qs)


@transaction.atomic
def freeze_escrow_rows(event: Event) -> int:
    qs = EscrowPayment.objects.select_for_update().filter(
        event=event,
        status=EscrowPayment.STATUS_HELD,
    )
    n = 0
    for p in qs:
        p.status = EscrowPayment.STATUS_FROZEN
        p.save(update_fields=["status", "updated_at"])
        n += 1
    return n


@transaction.atomic
def debug_staff_wallet_credit(*, user: AbstractUser, amount: Decimal) -> UserWallet:
    """Local-only balance for staff when Razorpay keys are not configured."""
    from django.conf import settings
    from django.core.exceptions import PermissionDenied

    if not getattr(settings, "DEBUG", False) or not user.is_staff:
        raise PermissionDenied("Demo wallet credit is only for staff in DEBUG mode.")
    amount = _q2(amount)
    if amount <= 0 or amount > Decimal("50000"):
        raise ValidationError({"amount": "Demo credit must be between ₹0.01 and ₹50000."})
    uw, _ = UserWallet.objects.select_for_update().get_or_create(
        user=user, defaults={"currency": "INR"}
    )
    UserWallet.objects.filter(pk=uw.pk).update(balance=F("balance") + amount)
    WalletLedgerEntry.objects.create(
        user=user,
        amount=amount,
        kind=WalletLedgerEntry.KIND_TOP_UP,
        note="DEBUG staff demo credit (no Razorpay)",
    )
    return UserWallet.objects.get(pk=uw.pk)


@transaction.atomic
def credit_wallet_topup(
    *,
    user: AbstractUser,
    amount: Decimal,
    razorpay_order_id: str,
    razorpay_payment_id: str,
) -> None:
    uw = get_or_create_user_wallet(user)
    uw = UserWallet.objects.select_for_update().get(pk=uw.pk)
    amount = _q2(amount)
    UserWallet.objects.filter(pk=uw.pk).update(balance=F("balance") + amount)
    WalletLedgerEntry.objects.create(
        user=user,
        amount=amount,
        kind=WalletLedgerEntry.KIND_TOP_UP,
        note=f"Razorpay payment {razorpay_payment_id} order {razorpay_order_id}",
    )


@transaction.atomic
def request_payout(*, user: AbstractUser, amount: Decimal, note: str = "") -> WalletPayoutRequest:
    amount = _q2(amount)
    if amount <= 0:
        raise ValidationError({"amount": "Amount must be positive."})
    uw = UserWallet.objects.select_for_update().filter(user=user).first()
    if uw is None or uw.balance < amount:
        raise ValidationError({"detail": "Insufficient wallet balance for payout."})
    UserWallet.objects.filter(pk=uw.pk).update(balance=F("balance") - amount)
    pr = WalletPayoutRequest.objects.create(
        user=user,
        amount=amount,
        status=WalletPayoutRequest.STATUS_PENDING,
        note=note[:500],
    )
    WalletLedgerEntry.objects.create(
        user=user,
        amount=-amount,
        kind=WalletLedgerEntry.KIND_PAYOUT_REQUEST,
        payout_request=pr,
        note="Payout request — pending ops / bank transfer",
    )
    return pr


@transaction.atomic
def approve_payout(*, payout: WalletPayoutRequest, admin_user) -> WalletPayoutRequest:
    if payout.status != WalletPayoutRequest.STATUS_PENDING:
        raise ValidationError({"detail": "Payout is not pending."})
    payout.status = WalletPayoutRequest.STATUS_APPROVED
    payout.reviewed_by = admin_user
    payout.save(update_fields=["status", "reviewed_by", "updated_at"])
    return payout


@transaction.atomic
def mark_payout_processed_demo(*, payout: WalletPayoutRequest) -> WalletPayoutRequest:
    payout.status = WalletPayoutRequest.STATUS_PROCESSED
    payout.save(update_fields=["status", "updated_at"])
    WalletLedgerEntry.objects.create(
        user=payout.user,
        amount=Decimal("0"),
        kind=WalletLedgerEntry.KIND_PAYOUT_COMPLETED,
        payout_request=payout,
        note="Payout marked processed (wire Razorpay Payouts / NEFT in production)",
    )
    return payout


@transaction.atomic
def reject_payout(*, payout: WalletPayoutRequest, admin_user) -> WalletPayoutRequest:
    if payout.status != WalletPayoutRequest.STATUS_PENDING:
        raise ValidationError({"detail": "Payout is not pending."})
    amt = payout.amount
    uw = UserWallet.objects.select_for_update().get(user=payout.user)
    UserWallet.objects.filter(pk=uw.pk).update(balance=F("balance") + amt)
    payout.status = WalletPayoutRequest.STATUS_REJECTED
    payout.reviewed_by = admin_user
    payout.save(update_fields=["status", "reviewed_by", "updated_at"])
    WalletLedgerEntry.objects.create(
        user=payout.user,
        amount=amt,
        kind=WalletLedgerEntry.KIND_PAYOUT_REJECTED,
        payout_request=payout,
        note="Payout rejected — balance restored",
    )
    return payout


@transaction.atomic
def grievance_refund_to_user(grievance: EventGrievance) -> None:
    if grievance.status != EventGrievance.STATUS_PENDING:
        raise ValidationError({"detail": "Grievance already resolved."})
    event = grievance.event
    user = grievance.user
    pay = (
        EscrowPayment.objects.select_for_update()
        .filter(
            event=event,
            user=user,
            status__in=(EscrowPayment.STATUS_HELD, EscrowPayment.STATUS_FROZEN),
        )
        .first()
    )
    if not pay:
        grievance.status = EventGrievance.STATUS_REJECTED
        grievance.save(update_fields=["status", "updated_at"])
        raise ValidationError(
            {"detail": "No refundable escrow for this booking (already released or refunded)."}
        )
    amt = _q2(pay.amount)
    treasury = PlatformTreasury.objects.select_for_update().get(pk=1)
    if treasury.held_escrow_balance < amt:
        raise ValidationError(
            {"detail": "Treasury held balance does not cover this refund; reconcile manually."}
        )
    take = amt
    pay.status = EscrowPayment.STATUS_REFUNDED
    pay.save(update_fields=["status", "updated_at"])
    PlatformTreasury.objects.filter(pk=1).update(
        held_escrow_balance=F("held_escrow_balance") - take
    )
    uw, _ = UserWallet.objects.select_for_update().get_or_create(
        user=user,
        defaults={"currency": "INR"},
    )
    UserWallet.objects.filter(pk=uw.pk).update(balance=F("balance") + take)
    grievance.status = EventGrievance.STATUS_APPROVED_REFUND
    grievance.save(update_fields=["status", "updated_at"])
    WalletLedgerEntry.objects.create(
        user=user,
        amount=take,
        kind=WalletLedgerEntry.KIND_GRIEVANCE_REFUND,
        note=f"Grievance {grievance.pk} approved — refund to wallet",
    )


@transaction.atomic
def reject_grievance(grievance: EventGrievance) -> EventGrievance:
    if grievance.status != EventGrievance.STATUS_PENDING:
        raise ValidationError({"detail": "Grievance already resolved."})
    grievance.status = EventGrievance.STATUS_REJECTED
    grievance.save(update_fields=["status"])
    return grievance
