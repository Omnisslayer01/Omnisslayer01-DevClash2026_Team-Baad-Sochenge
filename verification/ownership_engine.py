"""
Ownership verification and trust scoring. Pure logic + repository calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import models as vmodels
from . import normalization, repositories
from .realism import maybe_random_not_found


@dataclass
class OwnershipResult:
    trust_score: int
    decision: str
    explanation: str
    data: dict
    subscores: dict[str, int] = field(default_factory=dict)
    fraud_hints: list[dict] = field(default_factory=list)


def _clamp(n: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, n))


def clamp_score(n: int) -> int:
    """Public clamp for downstream adjustments (e.g. fraud penalties)."""
    return _clamp(n)


def verify_ownership(
    *,
    cin: str,
    gstin: str,
    company_name_user: str,
    claimant_name: str,
    claimant_external_id: str,
    apply_random_not_found: bool = True,
) -> OwnershipResult:
    """
    Main evaluation. `apply_random_not_found` simulates rare registry inconsistencies.
    """
    cin_u = cin.strip().upper()
    gstin_u = gstin.strip().upper()

    company = repositories.get_company_by_cin(cin_u)
    tax = repositories.get_tax_by_gstin(gstin_u)

    if apply_random_not_found and company and maybe_random_not_found():
        company = None
    if apply_random_not_found and tax and maybe_random_not_found():
        tax = None

    sub = {
        "tax_record": 0,
        "company_record": 0,
        "name_consistency": 0,
        "director_match": 0,
    }
    notes: list[str] = []

    # --- Company record ---
    if not company:
        sub["company_record"] = 0
        notes.append("Company ID not found in simulated MCA register.")
    elif company.status != vmodels.Company.STATUS_ACTIVE:
        sub["company_record"] = 8
        notes.append("Company found but status is not Active.")
    else:
        sub["company_record"] = 25

    # --- Tax record ---
    if not tax:
        sub["tax_record"] = 0
        notes.append("GSTIN not found in simulated tax register.")
    elif tax.status != vmodels.TaxRecord.STATUS_ACTIVE:
        sub["tax_record"] = 8
        notes.append("GSTIN found but registration is not Active.")
    else:
        sub["tax_record"] = 25

    # --- Cross-link CIN <-> GSTIN ---
    linkage_ok = True
    if company and tax:
        if tax.linked_cin and tax.linked_cin.upper() != cin_u:
            linkage_ok = False
            sub["tax_record"] = min(sub["tax_record"], 10)
            sub["company_record"] = min(sub["company_record"], 10)
            notes.append("GSTIN is linked to a different company ID in the dataset.")

    # --- Name consistency (user vs registries) ---
    sims: list[float] = []
    if company:
        sims.append(
            normalization.name_similarity(company_name_user, company.legal_name)
        )
    if tax:
        sims.append(normalization.name_similarity(company_name_user, tax.legal_name))
    if company and tax:
        inter = normalization.name_similarity(company.legal_name, tax.legal_name)
        sims.append(inter)
        if inter < 0.72:
            notes.append(
                "Legal name on tax record differs from MCA name (common real-world drift)."
            )

    best = max(sims) if sims else 0.0
    sub["name_consistency"] = int(round(best * 25))
    if best < 0.55:
        notes.append("Provided company name is weakly aligned with registry names.")

    name_mismatch_flag = bool(company and tax and best < 0.62)

    # --- Director match ---
    director_hit = False
    if company:
        for d in company.directors:
            if normalization.person_names_match(claimant_name, d):
                director_hit = True
                break
    sub["director_match"] = 25 if director_hit else 0
    if company and not director_hit:
        notes.append(
            "Claimant name does not closely match any director on file (fuzzy match)."
        )

    raw = sum(sub.values())
    trust_score = _clamp(raw)

    # Penalize inconsistent linkage heavily
    if not linkage_ok:
        trust_score = _clamp(trust_score - 35)

    decision = "Rejected"
    if trust_score >= 80 and director_hit and linkage_ok:
        if (
            company
            and tax
            and company.status == vmodels.Company.STATUS_ACTIVE
            and tax.status == vmodels.TaxRecord.STATUS_ACTIVE
        ):
            decision = "Verified"
        else:
            decision = "Partially Verified"
            notes.append("High match but one register is not Active.")
    elif trust_score >= 45:
        decision = "Partially Verified"
    else:
        decision = "Rejected"

    explanation = " ".join(notes) if notes else "All checks aligned."

    payload = {
        "cin": cin_u,
        "gstin": gstin_u,
        "registry_company": (
            {
                "legal_name": company.legal_name,
                "status": company.status,
                "directors": list(company.directors),
            }
            if company
            else None
        ),
        "registry_tax": (
            {
                "legal_name": tax.legal_name,
                "status": tax.status,
                "linked_cin": tax.linked_cin,
            }
            if tax
            else None
        ),
        "claimant_name": claimant_name.strip(),
        "name_similarity_best": round(best, 4),
    }

    return OwnershipResult(
        trust_score=trust_score,
        decision=decision,
        explanation=explanation,
        data=payload,
        subscores=sub,
        fraud_hints=[],
    )
