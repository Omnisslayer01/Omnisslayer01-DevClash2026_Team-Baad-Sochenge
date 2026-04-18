"""
Data access layer. Swap these functions for real HTTP clients later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.db.models import QuerySet

from . import models


@dataclass(frozen=True)
class CompanyDTO:
    cin: str
    legal_name: str
    status: str
    directors: tuple[str, ...]


@dataclass(frozen=True)
class TaxDTO:
    gstin: str
    legal_name: str
    status: str
    linked_cin: str | None


def get_company_by_cin(cin: str) -> CompanyDTO | None:
    qs: QuerySet[models.Company] = models.Company.objects.filter(cin__iexact=cin)
    company = qs.prefetch_related("directors").first()
    if not company:
        return None
    names = tuple(d.full_name for d in company.directors.all())
    return CompanyDTO(
        cin=company.cin,
        legal_name=company.legal_name,
        status=company.status,
        directors=names,
    )


def get_tax_by_gstin(gstin: str) -> TaxDTO | None:
    row = models.TaxRecord.objects.select_related("company").filter(
        gstin__iexact=gstin
    ).first()
    if not row:
        return None
    linked = row.company.cin if row.company_id else None
    return TaxDTO(
        gstin=row.gstin,
        legal_name=row.legal_name,
        status=row.status,
        linked_cin=linked,
    )


def list_directors_for_cin(cin: str) -> Iterable[str]:
    c = models.Company.objects.filter(cin__iexact=cin).first()
    if not c:
        return ()
    return [d.full_name for d in c.directors.all()]
