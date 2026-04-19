"""
Demo sandbox identity checks. Replace with a real KYC / Digilocker provider in production.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone


def verify_identity_sandbox(
    *,
    claim_type: str,
    full_name: str,
    document_hint: str = "",
) -> dict:
    """
    Returns {"verified": bool, "reference": str, "reason": str}.

    Demo rules:
    - Names containing "fake", "deny", or "[fail]" (case-insensitive) are rejected.
    - Otherwise approved with a synthetic reference.
    """
    name = (full_name or "").strip().lower()
    if any(x in name for x in ("fake", "deny", "[fail]")):
        return {
            "verified": False,
            "reference": "",
            "reason": "Sandbox: identity signals did not match (demo rejection).",
        }

    alphabet = string.ascii_uppercase + string.digits
    ref = "SANDBOX-" + "".join(secrets.choice(alphabet) for _ in range(10))
    return {
        "verified": True,
        "reference": ref,
        "reason": f"Sandbox OK ({claim_type}); document_hint={document_hint!r}",
    }


def mark_profile_sandbox_time(profile) -> None:
    profile.sandbox_verified_at = datetime.now(timezone.utc)
