"""
Shared ownership verification pipeline (used by JSON API and Django views).
"""

from __future__ import annotations

from typing import Any

from . import fraud_tracker, normalization, ownership_engine, repositories
from .realism import maybe_upstream_failure, simulated_delay_ms


def run_ownership_verification(
    *,
    cin: str,
    gstin: str,
    company_name: str,
    claimant_name: str,
    claimant_id: str,
    apply_realism: bool = True,
) -> dict[str, Any]:
    """
    Returns the same shape as POST /api/v1/verify/ownership/:
    { "success": true, "data": {...}, "trust_score": int, "decision": str }
    or { "success": false, "error": str } with optional "_http_status" for callers.
    """
    cin_u = (cin or "").strip().upper()
    gstin_u = (gstin or "").strip().upper()
    company_name = (company_name or "").strip()
    claimant_name = (claimant_name or "").strip()
    claimant_id = (claimant_id or "").strip()

    if not all([cin_u, gstin_u, company_name, claimant_name]):
        return {
            "success": False,
            "error": "Required fields: CIN, GSTIN, company name, and claimant name.",
            "_http_status": 400,
        }
    if not normalization.cin_pattern().match(cin_u):
        return {"success": False, "error": "Invalid CIN format.", "_http_status": 400}
    if not normalization.gstin_pattern().match(gstin_u):
        return {"success": False, "error": "Invalid GSTIN format.", "_http_status": 400}

    if apply_realism:
        simulated_delay_ms(180, 650)
        err = maybe_upstream_failure()
        if err:
            return {"success": False, "error": err, "_http_status": 503}

    res = ownership_engine.verify_ownership(
        cin=cin_u,
        gstin=gstin_u,
        company_name_user=company_name,
        claimant_name=claimant_name,
        claimant_external_id=claimant_id,
        apply_random_not_found=True,
    )

    company = repositories.get_company_by_cin(cin_u)
    tax = repositories.get_tax_by_gstin(gstin_u)
    best = 0.0
    if company:
        best = max(
            best, normalization.name_similarity(company_name, company.legal_name)
        )
    if tax:
        best = max(best, normalization.name_similarity(company_name, tax.legal_name))
    name_mismatch = best < 0.62

    fraud_tracker.record_claim(
        claimant_external_id=claimant_id,
        cin=cin_u,
        gstin=gstin_u,
    )
    signals = fraud_tracker.evaluate_and_flag(
        claimant_external_id=claimant_id,
        cin=cin_u,
        gstin=gstin_u,
        name_mismatch=name_mismatch,
    )

    penalty = 7 * len(signals)
    trust = ownership_engine.clamp_score(res.trust_score - penalty)

    decision = res.decision
    if trust < 45:
        decision = "Rejected"
    elif trust < 80 and decision == "Verified":
        decision = "Partially Verified"

    out_data = dict(res.data)
    out_data["explanation"] = res.explanation
    out_data["subscores"] = res.subscores
    out_data["fraud_signals"] = signals

    return {
        "success": True,
        "data": out_data,
        "trust_score": trust,
        "decision": decision,
    }
