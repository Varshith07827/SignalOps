"""Plain-English, JSON-ready views of an analysis: weekly numbers, regional top 5, early warnings, routing."""

from __future__ import annotations

import pandas as pd

from voice_of_store.brief import build_region_brief
from voice_of_store.config import BriefSettings
from voice_of_store.service import Analysis

SEVERITIES = ["critical", "high", "medium", "low"]
URGENT = {"critical", "high"}
ACTION_TEXT = {
    "Escalate to function head": "Tell the head of the team today",
    "Escalate to regional manager": "Tell the regional manager now",
    "Owner action": "Team fixes it within 3 days",
    "Owner weekly queue": "Team fixes it this week",
    "Weekly brief only": "Keep an eye on it",
}
TREND_TEXT = {"UP": "Rising", "DOWN": "Falling", "=": "Steady", "NEW": "New this week"}
ESCALATION_RULE = [
    {
        "when": "Critical: someone hurt or ill, allergic reaction, assault",
        "who": "Head of the team",
        "within": "24 hours",
    },
    {"when": "Early warning: unusual rise at one store", "who": "Regional manager", "within": "24 to 72 hours"},
    {"when": "High: safety, hygiene, allergens, food safety, staff misconduct", "who": "The team", "within": "3 days"},
    {"when": "Medium", "who": "The team", "within": "7 days"},
    {"when": "Low", "who": "Weekly summary only", "within": "-"},
]


def week_label(week: pd.Timestamp) -> str:
    return f"{week:%Y-%m-%d}"


def week_overview(analysis: Analysis, week: pd.Timestamp, region: str | None = None) -> dict:
    """Headline numbers for one week (optionally one region) and each team's problems by severity."""
    rows = analysis.records[analysis.records["week_start"] == week]
    flags = analysis.flags[analysis.flags["as_of_week_start"] == week_label(week)]
    if region is not None:
        rows = rows[rows["region"] == region]
        flags = flags[flags["store_id"].isin(set(rows["store"].dropna()))]
    action = rows[rows["actionable"] == 1]
    counts = action.groupby(["owner_function", "severity"]).size().unstack(fill_value=0)
    counts = counts.reindex(columns=SEVERITIES, fill_value=0)
    teams = [
        {"team": team, **{s: int(row[s]) for s in SEVERITIES}, "total": int(row.sum())}
        for team, row in counts.iterrows()
    ]
    teams.sort(key=lambda t: (-(t["critical"] + t["high"]), -t["total"], t["team"]))
    return {
        "messages": len(rows),
        "need_action": len(action),
        "urgent": int(action["severity"].isin(URGENT).sum()),
        "warnings": len(flags),
        "teams": teams,
    }


def region_top_issues(
    analysis: Analysis,
    region: str,
    week: pd.Timestamp,
    taxonomy: pd.DataFrame,
    stores: pd.DataFrame,
    settings: BriefSettings,
) -> list[dict]:
    """The region's top issues for the week, worded for a store-operations reader."""
    names = dict(zip(stores["store_id"], stores["store_name"], strict=True))
    items = build_region_brief(analysis.records, analysis.flags, region, week, taxonomy, names, settings)
    return [
        {
            "problem": item.issue_type,
            "team": item.owner_function,
            "severity": item.severity,
            "action": ACTION_TEXT.get(item.escalation, item.escalation),
            "incidents": item.incidents,
            "reports": item.reports,
            "last_week": item.last_week_incidents,
            "trend": TREND_TEXT.get(item.trend, item.trend),
            "early_warning": item.emerging,
            "stores": item.stores,
            "quotes": item.quotes,
        }
        for item in items
    ]


def early_warnings(analysis: Analysis, taxonomy: pd.DataFrame, stores: pd.DataFrame, quote_chars: int) -> list[dict]:
    """Every early warning, newest first, with the store's name and one example message."""
    if analysis.flags.empty:
        return []
    names = stores.set_index("store_id")
    text = analysis.records.set_index("feedback_id")["text"]
    warnings = []
    for flag in analysis.flags.itertuples(index=False):
        ids = flag.evidence_feedback_ids.split(";")
        example = str(text.get(ids[0], ""))
        warnings.append(
            {
                "week": flag.as_of_week_start,
                "store": str(names.loc[flag.store_id, "store_name"]) if flag.store_id in names.index else flag.store_id,
                "region": str(names.loc[flag.store_id, "region"]) if flag.store_id in names.index else "",
                "problem": str(taxonomy.loc[flag.issue_type_id, "issue_type"]),
                "team": str(taxonomy.loc[flag.issue_type_id, "owner_function"]),
                "reports": len(ids),
                "example": example if len(example) <= quote_chars else example[: quote_chars - 3].rstrip() + "...",
            }
        )
    warnings.sort(key=lambda w: (w["week"], w["reports"]), reverse=True)
    return warnings
