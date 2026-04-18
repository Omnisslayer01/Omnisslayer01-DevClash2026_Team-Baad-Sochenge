"""
Fraud analytics on top of OwnershipClaim + FraudSignal models.
"""

from __future__ import annotations

from . import models


def record_claim(
    *,
    claimant_external_id: str,
    cin: str,
    gstin: str,
) -> None:
    models.OwnershipClaim.objects.create(
        claimant_external_id=claimant_external_id or "anonymous",
        cin=cin.upper(),
        gstin=gstin.upper(),
    )


def log_signal(signal_type: str, detail: dict, severity: str = "medium") -> None:
    models.FraudSignal.objects.create(
        signal_type=signal_type, detail=detail, severity=severity
    )


def evaluate_and_flag(
    *,
    claimant_external_id: str,
    cin: str,
    gstin: str,
    name_mismatch: bool,
) -> list[dict]:
    """
    After a verification attempt, emit fraud rows when thresholds hit.
    Returns list of signal dicts for API consumers (audit).
    """
    emitted: list[dict] = []
    cid = claimant_external_id or "anonymous"

    if name_mismatch:
        log_signal(
            models.FraudSignal.SIGNAL_NAME_MISMATCH,
            {"cin": cin, "gstin": gstin, "claimant": cid},
            severity="low",
        )
        emitted.append(
            {
                "type": models.FraudSignal.SIGNAL_NAME_MISMATCH,
                "detail": {"cin": cin, "gstin": gstin},
            }
        )

    distinct_people = (
        models.OwnershipClaim.objects.filter(cin__iexact=cin)
        .values("claimant_external_id")
        .distinct()
        .count()
    )
    if distinct_people >= 2:
        log_signal(
            models.FraudSignal.SIGNAL_MULTI_CLAIM_CIN,
            {
                "cin": cin,
                "distinct_claimants": distinct_people,
                "latest_claimant": cid,
            },
            severity="high",
        )
        emitted.append(
            {
                "type": models.FraudSignal.SIGNAL_MULTI_CLAIM_CIN,
                "detail": {"distinct_claimants": distinct_people},
            }
        )

    reuse = models.OwnershipClaim.objects.filter(gstin__iexact=gstin).count()
    if reuse >= 4:
        log_signal(
            models.FraudSignal.SIGNAL_GSTIN_REUSE,
            {"gstin": gstin, "claim_count": reuse},
            severity="medium",
        )
        emitted.append(
            {
                "type": models.FraudSignal.SIGNAL_GSTIN_REUSE,
                "detail": {"claim_count": reuse},
            }
        )

    return emitted
