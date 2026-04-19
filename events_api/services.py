"""
Escrow, QR, geocoding, fraud, and access-control helpers for platform events.
Payment providers are abstracted — wire Stripe/Razorpay using env secrets (never hardcoded).
"""
from __future__ import annotations

import base64
import io
import logging
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import qrcode
import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

    from events_api.models import EscrowPayment, Event, EventEnrollment

logger = logging.getLogger(__name__)


def organizer_identity_allowed_for_events(user: AbstractUser) -> bool:
    """
    Access control: BLUE or GREEN trust badge OR government / verified-user identity flag.
    """
    from accounts.models import Profile

    try:
        profile: Profile = user.profile
    except Exception:
        return False
    if getattr(profile, "is_gov_id_verified", False) or getattr(
        profile, "is_verified_user", False
    ):
        return True
    tier = profile.trust_tier
    if tier in ("blue", "green"):
        return True
    return False


def geocode_venue(*, address: str, venue_name: str = "") -> dict[str, Any]:
    """Validate location via Google Geocoding API (requires GOOGLE_MAPS_API_KEY)."""
    key = (getattr(settings, "GOOGLE_MAPS_API_KEY", None) or "").strip()
    query = f"{venue_name} {address}".strip()
    if not query:
        raise ValidationError({"address": "Address is required for geocoding."})
    if not key:
        raise ValidationError(
            {
                "detail": "GOOGLE_MAPS_API_KEY is not configured.",
            }
        )
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    try:
        resp = requests.get(
            url,
            params={"address": query, "key": key},
            timeout=getattr(settings, "REQUESTS_TIMEOUT_SEC", 15),
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.exception("Geocoding request failed")
        raise ValidationError(
            {"address": "Unable to validate address with maps provider."}
        ) from exc
    data = resp.json()
    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        raise ValidationError(
            {"address": f"Geocoder error: {data.get('status', 'unknown')}"}
        )
    results = data.get("results") or []
    if not results:
        raise ValidationError({"address": "No results for this address."})
    loc = results[0]["geometry"]["location"]
    return {
        "latitude": Decimal(str(loc["lat"])),
        "longitude": Decimal(str(loc["lng"])),
        "formatted_address": results[0].get("formatted_address", query),
    }


def resolve_venue(
    *,
    address: str,
    venue_name: str = "",
    latitude: Decimal | float | str | None = None,
    longitude: Decimal | float | str | None = None,
) -> dict[str, Any]:
    """
    Prefer Google geocoding when configured; otherwise (dev) allow explicit coordinates
    when ALLOW_VENUE_WITHOUT_MAPS is True.
    """
    key = (getattr(settings, "GOOGLE_MAPS_API_KEY", None) or "").strip()
    if key:
        return geocode_venue(address=address, venue_name=venue_name)
    if getattr(settings, "ALLOW_VENUE_WITHOUT_MAPS", False):
        if latitude is None or longitude is None:
            raise ValidationError(
                {
                    "latitude": "Provide latitude and longitude when maps API is disabled.",
                    "longitude": "Provide latitude and longitude when maps API is disabled.",
                }
            )
        v = validate_coordinates(latitude, longitude)
        return {
            "latitude": v["latitude"],
            "longitude": v["longitude"],
            "formatted_address": address,
        }
    raise ValidationError(
        {
            "detail": "Configure GOOGLE_MAPS_API_KEY or set ALLOW_VENUE_WITHOUT_MAPS=1 "
            "with explicit coordinates (development only)."
        }
    )


def validate_coordinates(
    lat: Decimal | float | str, lng: Decimal | float | str
) -> dict[str, Decimal]:
    lat_d = Decimal(str(lat))
    lng_d = Decimal(str(lng))
    if not (-90 <= float(lat_d) <= 90 and -180 <= float(lng_d) <= 180):
        raise ValidationError({"latitude": "Coordinates out of range."})
    return {"latitude": lat_d, "longitude": lng_d}


def charge_and_hold_escrow(
    *,
    user: AbstractUser,
    event: Event,
    enrollment: EventEnrollment,
    amount: Decimal,
    currency: str = "INR",
) -> EscrowPayment:
    """Move funds from user wallet into platform escrow (wallet-backed booking)."""
    from events_api import wallet_services

    _ = currency  # INR only in demo
    return wallet_services.book_paid_enrollment(
        user=user, event=event, enrollment=enrollment, amount=amount
    )


def release_escrow_to_organizer(event: Event) -> int:
    """Release held escrow to organizer wallet."""
    from events_api import wallet_services

    return wallet_services.release_event_escrow_to_organizer_wallet(event)


def refund_escrow_payments(event: Event) -> int:
    from events_api import wallet_services

    return wallet_services.refund_escrow_rows_to_wallets(event)


def freeze_escrow_payments(event: Event) -> int:
    from events_api import wallet_services

    return wallet_services.freeze_escrow_rows(event)


def parse_qr_payload(raw: str) -> tuple[uuid.UUID, str | None]:
    """QR may be `public_id` or `public_id|attendance_key`."""
    raw = (raw or "").strip()
    if "|" in raw:
        left, right = raw.split("|", 1)
        return uuid.UUID(left.strip()), right.strip() or None
    return uuid.UUID(raw), None


def enrollment_check_in(
    *,
    event: Event,
    organizer: AbstractUser,
    public_id: uuid.UUID | None = None,
    qr_payload: str | None = None,
    attendance_key: str | None = None,
) -> EventEnrollment:
    from events_api.models import EventEnrollment

    if event.organizer_id != organizer.id:
        raise PermissionDenied("Only the event organizer can check in attendees.")
    if event.status != Event.STATUS_ACTIVE:
        raise ValidationError({"detail": "Event is not active for check-in."})
    if qr_payload:
        pid, key_from_qr = parse_qr_payload(qr_payload)
        attendance_key = key_from_qr or attendance_key
    else:
        pid = public_id
        if pid is None:
            raise ValidationError({"detail": "Provide public_id or qr_payload."})
    with transaction.atomic():
        try:
            en = EventEnrollment.objects.select_for_update().get(event=event, public_id=pid)
        except EventEnrollment.DoesNotExist as exc:
            raise ValidationError({"public_id": "Unknown enrollment."}) from exc
        if attendance_key and en.attendance_key != attendance_key:
            raise ValidationError({"attendance_key": "Invalid attendance key."})
        if en.checked_in_quantity >= en.quantity:
            return en
        en.checked_in_quantity += 1
        if en.checked_in_quantity == 1:
            en.checked_in_at = timezone.now()
        en.save(update_fields=["checked_in_quantity", "checked_in_at"])
    return en


def check_in_ratio(event: Event) -> float:
    total_q = event.enrollments.aggregate(s=Sum("quantity"))["s"] or 0
    if total_q == 0:
        return 0.0
    checked = event.enrollments.aggregate(s=Sum("checked_in_quantity"))["s"] or 0
    return float(checked) / float(total_q)


def fraud_report_ratio(event: Event) -> float:
    enrolled_users = event.enrollments.values("user").distinct().count()
    if enrolled_users == 0:
        return 0.0
    reporters = event.fraud_reports.values("user").distinct().count()
    return reporters / enrolled_users


def evaluate_fraud_and_maybe_flag(event: Event) -> None:
    from events_api.models import Event

    event = Event.objects.get(pk=event.pk)
    if event.status != Event.STATUS_ACTIVE:
        return
    if fraud_report_ratio(event) >= 0.5:
        freeze_escrow_payments(event)
        event.status = Event.STATUS_FLAGGED
        event.save(update_fields=["status", "updated_at"])
        refund_escrow_payments(event)


def maybe_release_escrow_after_completion(event: Event) -> None:
    from events_api.models import Event

    if event.status != Event.STATUS_COMPLETED:
        return
    if check_in_ratio(event) >= 0.5:
        release_escrow_to_organizer(event)
    else:
        refund_escrow_payments(event)


def generate_qr_png_base64(public_id: uuid.UUID) -> str:
    return generate_qr_png_base64_from_string(str(public_id))


def generate_qr_png_base64_from_string(payload: str) -> str:
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def complete_event_and_settle(event: Event) -> None:
    from events_api.models import Event

    with transaction.atomic():
        e = Event.objects.select_for_update().get(pk=event.pk)
        if e.status != Event.STATUS_ACTIVE:
            return
        e.status = Event.STATUS_COMPLETED
        e.save(update_fields=["status", "updated_at"])
        maybe_release_escrow_after_completion(e)
