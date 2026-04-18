"""
JSON verification API — mimics external registry style responses.
"""

from __future__ import annotations

import json
from typing import Any

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from functools import wraps

from . import models as vmodels, normalization, repositories
from .facade import run_ownership_verification
from .realism import maybe_upstream_failure, simulated_delay_ms


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"success": False, "error": message}, status=status)


def _read_json(request) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def _confidence_for_tax_status(status: str) -> tuple[int, str]:
    if status == vmodels.TaxRecord.STATUS_ACTIVE:
        return 92, "Verified"
    if status == vmodels.TaxRecord.STATUS_SUSPENDED:
        return 55, "Partially Verified"
    return 28, "Partially Verified"


def _confidence_for_company_status(status: str) -> tuple[int, str]:
    if status == vmodels.Company.STATUS_ACTIVE:
        return 92, "Verified"
    return 35, "Partially Verified"


def _is_boss_company_user(request) -> bool:
    user = request.user
    if not getattr(user, "is_authenticated", False):
        return False
    profile = getattr(user, "profile", None)
    return bool(profile and profile.is_boss and user.role == "company")


def boss_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not _is_boss_company_user(request):
            return _json_error(
                "Only verified company bosses can access this endpoint.",
                status=403,
            )
        return view_func(request, *args, **kwargs)

    return _wrapped


@csrf_exempt
@require_http_methods(["POST"])
@boss_required
def verify_tax_id(request):
    """Verify GSTIN against internal tax register."""
    body = _read_json(request)
    gstin = (body.get("gstin") or "").strip().upper()
    if not gstin:
        return _json_error("Field `gstin` is required.")
    if not normalization.gstin_pattern().match(gstin):
        return _json_error(
            "Invalid GSTIN format (expected 15-character Indian GSTIN pattern)."
        )

    simulated_delay_ms(100, 420)
    err = maybe_upstream_failure()
    if err:
        return _json_error(err, status=503)

    row = repositories.get_tax_by_gstin(gstin)
    if row is None:
        return _json_error("GSTIN not found in simulated registry.", status=404)

    conf, decision = _confidence_for_tax_status(row.status)
    data = {
        "gstin": row.gstin,
        "legal_name": row.legal_name,
        "status": row.status,
        "linked_cin": row.linked_cin,
    }
    return JsonResponse(
        {
            "success": True,
            "data": data,
            "trust_score": conf,
            "decision": decision,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
@boss_required
def verify_company_id(request):
    """Verify CIN against internal company register."""
    body = _read_json(request)
    cin = (body.get("cin") or "").strip().upper()
    if not cin:
        return _json_error("Field `cin` is required.")
    if not normalization.cin_pattern().match(cin):
        return _json_error("Invalid CIN format (expected 21-character CIN).")

    simulated_delay_ms(90, 400)
    err = maybe_upstream_failure()
    if err:
        return _json_error(err, status=503)

    row = repositories.get_company_by_cin(cin)
    if row is None:
        return _json_error("Company ID not found in simulated MCA register.", status=404)

    conf, decision = _confidence_for_company_status(row.status)
    data = {
        "cin": row.cin,
        "legal_name": row.legal_name,
        "status": row.status,
        "directors": list(row.directors),
    }
    return JsonResponse(
        {
            "success": True,
            "data": data,
            "trust_score": conf,
            "decision": decision,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
@boss_required
def verify_ownership_view(request):
    """
    Main ownership check: company + tax + names + director fuzzy match.
    """
    body = _read_json(request)
    result = run_ownership_verification(
        cin=(body.get("cin") or ""),
        gstin=(body.get("gstin") or ""),
        company_name=(body.get("company_name") or ""),
        claimant_name=(body.get("claimant_name") or ""),
        claimant_id=(body.get("claimant_id") or str(request.user.id)),
        apply_realism=True,
    )
    if not result.get("success"):
        status = int(result.get("_http_status") or 400)
        err = result.get("error", "Error")
        payload = {"success": False, "error": err}
        return JsonResponse(payload, status=status)

    return JsonResponse(
        {
            "success": True,
            "data": result["data"],
            "trust_score": result["trust_score"],
            "decision": result["decision"],
        }
    )
