"""
Razorpay Orders + payment verification (test/live keys from env).
https://razorpay.com/docs/api/orders/create/
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings
from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)


def _auth() -> tuple[str, str] | None:
    key = (getattr(settings, "RAZORPAY_KEY_ID", None) or "").strip()
    secret = (getattr(settings, "RAZORPAY_KEY_SECRET", None) or "").strip()
    if not key or not secret:
        return None
    return key, secret


def razorpay_configured() -> bool:
    return _auth() is not None


def get_publishable_key_id() -> str | None:
    auth = _auth()
    return auth[0] if auth else None


def create_order(*, amount_inr: Decimal, receipt: str, notes: dict[str, str] | None = None) -> dict[str, Any]:
    """Create a Razorpay order (amount in INR → paise). Returns order dict including id."""
    auth = _auth()
    if not auth:
        raise ValidationError(
            {
                "detail": "Razorpay is not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.",
            }
        )
    key, secret = auth
    amount_paise = int((amount_inr * Decimal(100)).quantize(Decimal("1")))
    if amount_paise < 100:
        raise ValidationError({"amount": "Minimum top-up is ₹1.00 (100 paise)."})
    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": (receipt or "rcpt")[:40],
        "payment_capture": 1,
        "notes": notes or {},
    }
    r = requests.post(
        "https://api.razorpay.com/v1/orders",
        json=payload,
        auth=(key, secret),
        timeout=getattr(settings, "REQUESTS_TIMEOUT_SEC", 30),
    )
    if not r.ok:
        logger.warning("Razorpay order failed: %s %s", r.status_code, r.text)
        raise ValidationError({"detail": f"Razorpay order failed: {r.text[:200]}"})
    return r.json()


def verify_payment_signature(*, order_id: str, payment_id: str, signature: str) -> bool:
    secret = (_auth() or ("", ""))[1]
    if not secret:
        return False
    body = f"{order_id}|{payment_id}".encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature or "")


def fetch_payment(payment_id: str) -> dict[str, Any]:
    auth = _auth()
    if not auth:
        raise ValidationError({"detail": "Razorpay not configured."})
    key, secret = auth
    r = requests.get(
        f"https://api.razorpay.com/v1/payments/{payment_id}",
        auth=(key, secret),
        timeout=getattr(settings, "REQUESTS_TIMEOUT_SEC", 30),
    )
    if not r.ok:
        logger.warning("Razorpay fetch payment failed: %s", r.text)
        raise ValidationError({"detail": "Could not fetch payment from Razorpay."})
    return r.json()


def refund_payment(*, payment_id: str, amount_paise: int | None = None) -> dict[str, Any]:
    """Refund a captured payment (partial if amount_paise set)."""
    auth = _auth()
    if not auth:
        raise ValidationError({"detail": "Razorpay not configured."})
    key, secret = auth
    payload: dict[str, Any] = {}
    if amount_paise is not None:
        payload["amount"] = amount_paise
    r = requests.post(
        f"https://api.razorpay.com/v1/payments/{payment_id}/refund",
        json=payload or {},
        auth=(key, secret),
        timeout=getattr(settings, "REQUESTS_TIMEOUT_SEC", 30),
    )
    if not r.ok:
        logger.warning("Razorpay refund failed: %s", r.text)
        raise ValidationError({"detail": f"Razorpay refund failed: {r.text[:200]}"})
    return r.json()
