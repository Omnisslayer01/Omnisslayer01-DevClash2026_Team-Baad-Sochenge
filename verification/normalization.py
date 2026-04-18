"""
Name and identifier normalization for India-style company data.
Keeps logic framework-agnostic for reuse with real API adapters.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Common suffix noise (order matters: longer phrases first).
_SUFFIX_PATTERNS = [
    r"\bprivate\s+limited\b",
    r"\bpvt\.?\s*ltd\.?\b",
    r"\blimited\b",
    r"\bltd\.?\b",
    r"\bllp\b",
    r"\binc\.?\b",
    r"\bcorporation\b",
    r"\bcorp\.?\b",
]


def normalize_company_name(value: str) -> str:
    """Lowercase, strip legal suffix noise, collapse whitespace."""
    if not value:
        return ""
    s = value.lower().strip()
    for pat in _SUFFIX_PATTERNS:
        s = re.sub(pat, " ", s, flags=re.IGNORECASE)
    s = re.sub(r"[^\w\s&]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def gstin_pattern() -> re.Pattern[str]:
    # Indian GSTIN: 15 chars; simplified check for demo.
    return re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-ZA-Z]{1}$")


def cin_pattern() -> re.Pattern[str]:
    # CIN: 21 alphanumeric (L / U + 5 digits + 2 alpha state + 4 year + 3 type + 6 seq).
    return re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")


def name_similarity(a: str, b: str) -> float:
    """0.0–1.0 fuzzy match on normalized tokens."""
    na, nb = normalize_company_name(a), normalize_company_name(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def person_name_tokens(name: str) -> set[str]:
    """Loose token set for director vs claimant comparison."""
    if not name:
        return set()
    s = re.sub(r"[^\w\s]", " ", name.lower())
    parts = {p for p in s.split() if len(p) > 1}
    return parts


def person_names_match(claimant: str, director: str, threshold: float = 0.86) -> bool:
    """
    Match a person's name to a director line: high similarity OR strong token overlap.
    Handles 'R. K. Sharma' vs 'Rajesh Kumar Sharma' partially via fuzzy ratio.
    """
    c, d = claimant.strip(), director.strip()
    if not c or not d:
        return False
    ratio = SequenceMatcher(None, c.lower(), d.lower()).ratio()
    if ratio >= threshold:
        return True
    ct, dt = person_name_tokens(c), person_name_tokens(d)
    if not ct or not dt:
        return False
    inter = len(ct & dt)
    union = len(ct | dt)
    jaccard = inter / union if union else 0.0
    return jaccard >= 0.5 and inter >= 2
