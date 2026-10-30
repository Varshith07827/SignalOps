"""Owner routing and the escalation rule.

Escalation rule (also stated in the README):
* critical -> escalate to the owning function's head within 24 h;
* high -> owning function, action within 72 h;
* an emerging-issue flag -> regional manager + owning function, whatever the record severities;
* medium -> owning function's weekly queue (7 days); low -> weekly brief only.
Only actionable records are routed: praise, chatter, spam and unroutable rants never reach an owner.
"""

from __future__ import annotations

import pandas as pd

from voice_of_store.config import RoutingSettings

NOT_ROUTED = "Not routed"


def escalation_level(severity: str, emerging: bool) -> str:
    """Human-readable escalation tier for one issue."""
    if severity == "critical":
        return "Escalate to function head"
    if emerging:
        return "Escalate to regional manager"
    if severity == "high":
        return "Owner action"
    if severity == "medium":
        return "Owner weekly queue"
    return "Weekly brief only"


def sla_hours(severity: str, settings: RoutingSettings) -> int | None:
    """Response deadline in hours, or None for low severity (no SLA, tracked in the brief)."""
    return {
        "critical": settings.sla_hours_critical,
        "high": settings.sla_hours_high,
        "medium": settings.sla_hours_medium,
    }.get(severity)


def route_records(labelled: pd.DataFrame, taxonomy: pd.DataFrame, settings: RoutingSettings) -> pd.DataFrame:
    """Add owner_function, escalation and sla_hours columns to record-level predictions."""
    routed = labelled.copy()
    owner = routed["issue_type_id"].map(taxonomy["owner_function"])
    routed["owner_function"] = owner.where(routed["actionable"] == 1, NOT_ROUTED)
    routed["escalation"] = [
        escalation_level(sev, False) if act == 1 else NOT_ROUTED
        for sev, act in zip(routed["severity"], routed["actionable"], strict=True)
    ]
    routed["sla_hours"] = [
        sla_hours(sev, settings) if act == 1 else None
        for sev, act in zip(routed["severity"], routed["actionable"], strict=True)
    ]
    return routed
