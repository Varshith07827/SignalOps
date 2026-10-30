"""Weekly one-page brief per region: top issues, evidence quotes, affected stores and a trend arrow."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from voice_of_store.config import BriefSettings
from voice_of_store.policy import SEVERITY_RANK
from voice_of_store.routing import escalation_level

# How much one incident counts when ranking issues.
SEVERITY_WEIGHT = {"low": 1.0, "medium": 2.0, "high": 4.0, "critical": 8.0}
EMERGING_BONUS = 10.0
TREND_BAND = 0.2
NATIONAL_DIGITAL = "National (online & app)"


@dataclass(frozen=True)
class BriefItem:
    issue_type_id: str
    issue_type: str
    owner_function: str
    severity: str
    escalation: str
    incidents: int
    reports: int
    last_week_incidents: int
    trend: str
    emerging: bool
    stores: list[str]
    quotes: list[str]
    priority: float


def trend_arrow(current: int, previous: int) -> str:
    """Arrow comparing this week's unique incidents with last week's."""
    if previous == 0:
        return "NEW" if current > 0 else "="
    change = (current - previous) / previous
    if change > TREND_BAND:
        return "UP"
    if change < -TREND_BAND:
        return "DOWN"
    return "="


def attach_regions(routed: pd.DataFrame, stores: pd.DataFrame) -> pd.Series:
    """Region of each record's store; storeless online/app issues go to the national digital brief."""
    region = routed["store"].map(stores.set_index("store_id")["region"])
    return region.fillna(NATIONAL_DIGITAL)


def build_region_brief(
    routed: pd.DataFrame,
    flags: pd.DataFrame,
    region: str,
    week_start: pd.Timestamp,
    taxonomy: pd.DataFrame,
    store_names: dict[str, str],
    settings: BriefSettings,
) -> list[BriefItem]:
    """Top issues for one region and week. ``routed`` needs region, incident_id and the prediction columns."""
    actionable = routed[(routed["actionable"] == 1) & (routed["region"] == region)]
    this_week = actionable[actionable["week_start"] == week_start]
    last_week = actionable[actionable["week_start"] == week_start - pd.Timedelta(weeks=1)]
    week_flags = flags[pd.to_datetime(flags["as_of_week_start"]) == week_start]
    emerging_types = set(week_flags.loc[week_flags["store_id"].isin(this_week["store"]), "issue_type_id"])

    items = []
    for issue_type, group in this_week.groupby("issue_type_id"):
        incidents = group.drop_duplicates("incident_id")
        severity = max(group["severity"], key=SEVERITY_RANK.__getitem__)
        emerging = issue_type in emerging_types
        priority = float(incidents["severity"].map(SEVERITY_WEIGHT).sum()) + (EMERGING_BONUS if emerging else 0.0)
        previous = last_week.loc[last_week["issue_type_id"] == issue_type, "incident_id"].nunique()
        items.append(
            BriefItem(
                issue_type_id=issue_type,
                issue_type=str(taxonomy.loc[issue_type, "issue_type"]),
                owner_function=str(taxonomy.loc[issue_type, "owner_function"]),
                severity=severity,
                escalation=escalation_level(severity, emerging),
                incidents=len(incidents),
                reports=len(group),
                last_week_incidents=int(previous),
                trend=trend_arrow(len(incidents), int(previous)),
                emerging=emerging,
                stores=sorted({store_names.get(s, s) for s in group["store"].dropna()}),
                quotes=_pick_quotes(group, settings),
                priority=priority,
            )
        )
    items.sort(key=lambda item: (-item.priority, item.issue_type_id))
    return items[: settings.top_n]


def _pick_quotes(group: pd.DataFrame, settings: BriefSettings) -> list[str]:
    """Most severe, most confidently classified reports, one per incident, trimmed for a one-page brief."""
    ranked = group.assign(rank=group["severity"].map(SEVERITY_RANK)).sort_values(
        ["rank", "issue_confidence", "feedback_id"], ascending=[False, False, True]
    )
    texts = ranked.drop_duplicates("incident_id")["text"].head(settings.quotes_per_issue)
    limit = settings.quote_max_chars
    return [t if len(t) <= limit else t[: limit - 3].rstrip() + "..." for t in texts]


def render_markdown(region: str, week_start: pd.Timestamp, items: list[BriefItem]) -> str:
    """Render one region's brief as Markdown (the format of the files in the outputs folder)."""
    week_end = week_start + pd.Timedelta(days=6)
    lines = [
        f"# Voice-of-Store weekly brief: {region}",
        f"Week {week_start:%d %b %Y} to {week_end:%d %b %Y}. Counts are unique incidents (cross-channel duplicates "
        "merged); trend compares with the previous week.",
        "",
    ]
    if not items:
        lines.append("No actionable issues this week.")
    for rank, item in enumerate(items, start=1):
        flag = " | EMERGING" if item.emerging else ""
        lines += [
            f"## {rank}. {item.issue_type} ({item.issue_type_id}){flag}",
            f"- Owner: **{item.owner_function}**, severity **{item.severity}**, action: {item.escalation}",
            f"- {item.incidents} incidents ({item.reports} reports), trend {item.trend} "
            f"(last week {item.last_week_incidents})",
            f"- Stores: {', '.join(item.stores) if item.stores else 'online / app (no store)'}",
        ]
        lines += [f'  > "{quote}"' for quote in item.quotes]
        lines.append("")
    return "\n".join(lines)
