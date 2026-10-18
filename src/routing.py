"""Ownership routing and recommended actions (PROVISIONAL mappings).

The category -> owner mapping lives in ``taxonomy.CATEGORIES``. It is our own
assumption for the demonstration and must be replaced by official
organisational rules when they become available.
"""
from __future__ import annotations

from src.taxonomy import CATEGORY_BY_CODE, OWNERS, UNCLASSIFIED

TRIAGE_OWNER = "Triage (unassigned)"


def assign_owner(category: str) -> tuple[str, str | None]:
    """Return (primary owner, secondary owner) for a predicted category."""
    cat = CATEGORY_BY_CODE.get(category)
    if cat is None or category == UNCLASSIFIED:
        return TRIAGE_OWNER, None
    return cat.owner, cat.secondary_owner


def recommended_action(category: str, case_type: str, severity: str, mandatory: bool) -> str:
    cat = CATEGORY_BY_CODE.get(category)
    base = cat.action if cat else "Triage the report manually and assign a category."
    steps = []
    if mandatory and severity == "Critical":
        steps.append("Verify the allegation within 24h and preserve all evidence; do not treat it as "
                     "confirmed until verified.")
    elif mandatory:
        steps.append("Review within 72h under policy; record the verification outcome.")
    if case_type == "Emerging trend":
        steps.append("Investigate why reports at this store are rising faster than its baseline and the "
                     "network trend.")
    steps.append(base)
    return " ".join(steps)


def valid_owners() -> list[str]:
    return list(OWNERS) + [TRIAGE_OWNER]
