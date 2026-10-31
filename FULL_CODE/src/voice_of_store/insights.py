"""Plain-English, JSON-ready views of an analysis: weekly numbers, regional top 5, early warnings, routing."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from voice_of_store.brief import build_region_brief
from voice_of_store.config import BriefSettings, RoutingSettings
from voice_of_store.policy import STORELESS_ROUTABLE_TYPES
from voice_of_store.routing import escalation_level, sla_hours
from voice_of_store.service import Analysis

SEVERITIES = ["critical", "high", "medium", "low"]
SEVERITY_RANK = {severity: rank for rank, severity in enumerate(SEVERITIES)}
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


LANGUAGE_TEXT = {"english": "English", "hinglish": "Hinglish", "tamil": "Tamil", "marathi": "Marathi"}
CHANNEL_TEXT = {
    "online_review": "Online review",
    "in_app": "App",
    "staff_shift_note": "Staff note",
    "call_centre_ticket": "Call centre",
}
NO_STORE = "Online or app (no store)"
# Short names that fit inside a bubble on the store board. Unknown types fall back to the start of their name.
SHORT_PROBLEM = {
    "IT01": "Checkout queue",
    "IT02": "Understaffing",
    "IT03": "Unhelpful staff",
    "IT04": "Staff misconduct",
    "IT05": "Staff welfare",
    "IT06": "Hygiene lapse",
    "IT07": "Untidy store",
    "IT08": "Safety hazard",
    "IT09": "Roof leak",
    "IT10": "Cold-chain failure",
    "IT11": "Equipment breakdown",
    "IT12": "Carry bags",
    "IT13": "Parking & timings",
    "IT14": "Out of stock",
    "IT15": "Poor fresh produce",
    "IT16": "Expired product",
    "IT17": "Contamination",
    "IT18": "Allergen labelling",
    "IT19": "Price mismatch",
    "IT20": "Offer not applied",
    "IT21": "Own-brand quality",
    "IT22": "Product not stocked",
    "IT23": "Late delivery",
    "IT24": "Wrong items",
    "IT25": "Damaged delivery",
    "IT26": "App bug",
    "IT27": "Payment failure",
    "IT28": "Refund pending",
    "IT29": "Loyalty points",
    "IT30": "Billing error",
}
# Rough neighbourhood locations for the stores in store_master.csv, used only by the map.
LOCATIONS_FILE = Path(__file__).with_name("store_locations.csv")


def review_result(label: dict, taxonomy: pd.DataFrame, stores: pd.DataFrame, routing: RoutingSettings) -> dict:
    """Word the label for one new message the way the dashboard shows it."""
    type_id = label["issue_type_id"]
    names = dict(zip(stores["store_id"], stores["store_name"], strict=True))
    no_store = "No store (online or app)"
    result = {
        "problem": str(taxonomy.loc[type_id, "issue_type"]),
        "issue_type_id": type_id,
        "severity": label["severity"],
        "needs_action": bool(label["actionable"]),
        "confidence": label["confidence"],
        "language": LANGUAGE_TEXT.get(label["language"], label["language"]),
        "store": names.get(label["store"], no_store) if label["store"] else no_store,
    }
    if label["actionable"]:
        hours = sla_hours(label["severity"], routing)
        result |= {
            "team": str(taxonomy.loc[type_id, "owner_function"]),
            "action": ACTION_TEXT[escalation_level(label["severity"], emerging=False)],
            "deadline": f"{hours} hours" if hours else "No deadline",
        }
    elif type_id.startswith("NI"):
        result["reason"] = "Praise, a general comment or spam, so nobody needs to act."
    elif not label["store"] and type_id not in STORELESS_ROUTABLE_TYPES:
        result["reason"] = "No store is given, so it can't be sent to a store team. Pick the store and check again."
    else:
        result["reason"] = "Too general to act on. Details like what, where and when make it actionable."
    return result


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
            "issue_type_id": item.issue_type_id,
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
                "store_id": flag.store_id,
                "issue_type_id": flag.issue_type_id,
                "store": str(names.loc[flag.store_id, "store_name"]) if flag.store_id in names.index else flag.store_id,
                "region": str(names.loc[flag.store_id, "region"]) if flag.store_id in names.index else "",
                "problem": str(taxonomy.loc[flag.issue_type_id, "issue_type"]),
                "team": str(taxonomy.loc[flag.issue_type_id, "owner_function"]),
                "reports": len(ids),
                "example": _short(example, quote_chars),
            }
        )
    warnings.sort(key=lambda w: (w["week"], w["reports"]), reverse=True)
    return warnings


def _short(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 3].rstrip() + "..."


def _worst(severities: pd.Series) -> str:
    return min(severities, key=SEVERITY_RANK.__getitem__)


def _case(group: pd.DataFrame, taxonomy: pd.DataFrame, names: dict, flagged: set, quote_chars: int) -> dict:
    """One case from the reports of one incident, sorted oldest first."""
    first = group.iloc[0]
    severity = _worst(group["severity"])
    hours = group["sla_hours"].dropna().min() if group["sla_hours"].notna().any() else None
    store = first["store"] if isinstance(first["store"], str) else None
    opened = first["created_at"]
    return {
        "ref": str(first["incident_id"]),
        "store_id": store,
        "issue_type_id": str(first["issue_type_id"]),
        "problem": str(taxonomy.loc[first["issue_type_id"], "issue_type"]),
        "team": str(first["owner_function"]),
        "severity": severity,
        "action": ACTION_TEXT[escalation_level(severity, emerging=False)],
        "store": names.get(store, store) if store else NO_STORE,
        "opened": f"{opened:%Y-%m-%dT%H:%M}",
        "due": None if hours is None else f"{opened + pd.Timedelta(hours=float(hours)):%Y-%m-%dT%H:%M}",
        "reports": len(group),
        "channels": sorted({CHANNEL_TEXT.get(c, c) for c in group["channel"]}),
        "early_warning": (store, first["issue_type_id"]) in flagged,
        "quote": _short(str(first["text"]), quote_chars),
    }


def case_list(
    analysis: Analysis,
    week: pd.Timestamp,
    taxonomy: pd.DataFrame,
    stores: pd.DataFrame,
    quote_chars: int,
    *,
    team: str | None = None,
    region: str | None = None,
    store: str | None = None,
    issue_type_id: str | None = None,
) -> dict:
    """Every case to act on in the week, most urgent first, for one team, region, store or problem.

    Reports of one incident (same store and problem within the dedup window) are one case.
    """
    records = analysis.records
    keep = (records["week_start"] == week) & (records["actionable"] == 1)
    filters = {"owner_function": team, "region": region, "store": store, "issue_type_id": issue_type_id}
    for column, value in filters.items():
        if value is not None:
            keep &= records[column] == value
    names = dict(zip(stores["store_id"], stores["store_name"], strict=True))
    week_flags = analysis.flags[analysis.flags["as_of_week_start"] == week_label(week)]
    flagged = set(zip(week_flags["store_id"], week_flags["issue_type_id"], strict=True))
    incidents = records[keep].sort_values("created_at").groupby("incident_id", sort=False)
    cases = [_case(group, taxonomy, names, flagged, quote_chars) for _, group in incidents]
    cases.sort(key=lambda c: (SEVERITY_RANK[c["severity"]], not c["early_warning"], c["due"] or "~", c["opened"]))
    counts = {s: sum(c["severity"] == s for c in cases) for s in SEVERITIES}
    return {"cases": cases, "counts": counts}


def incident_case(
    analysis: Analysis, ref: str, taxonomy: pd.DataFrame, stores: pd.DataFrame, quote_chars: int
) -> dict | None:
    """One case found in the feedback, with every message that belongs to it (None if there is no such case)."""
    records = analysis.records
    group = records[(records["incident_id"] == ref) & (records["actionable"] == 1)].sort_values("created_at")
    if group.empty:
        return None
    week = group["week_start"].iloc[0]
    week_flags = analysis.flags[analysis.flags["as_of_week_start"] == week_label(week)]
    flagged = set(zip(week_flags["store_id"], week_flags["issue_type_id"], strict=True))
    names = dict(zip(stores["store_id"], stores["store_name"], strict=True))
    case = _case(group, taxonomy, names, flagged, quote_chars)
    case["week"] = week_label(week)
    case["messages"] = [
        {
            "at": f"{row.created_at:%Y-%m-%dT%H:%M}",
            "channel": CHANNEL_TEXT.get(row.channel, row.channel),
            "language": LANGUAGE_TEXT.get(row.language, row.language),
            "text": str(row.text),
        }
        for row in group.itertuples(index=False)
    ]
    return case


def load_store_locations(path: Path = LOCATIONS_FILE) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"store_id": str})


def short_problem(type_id: str, name: str) -> str:
    return SHORT_PROBLEM.get(type_id) or name.split(" (")[0].split(" / ")[0]


def _store_problems(rows: pd.DataFrame, taxonomy: pd.DataFrame) -> list[dict]:
    """A store's problems this week, most severe and most frequent first."""
    problems = [
        {
            "issue_type_id": type_id,
            "problem": str(taxonomy.loc[type_id, "issue_type"]),
            "short": short_problem(type_id, str(taxonomy.loc[type_id, "issue_type"])),
            "severity": _worst(group["severity"]),
            "cases": int(group["incident_id"].nunique()),
        }
        for type_id, group in rows.groupby("issue_type_id")
    ]
    problems.sort(key=lambda p: (SEVERITY_RANK[p["severity"]], -p["cases"], p["problem"]))
    return problems


def _last_solved(history: pd.DataFrame, store: str, quiet_since: pd.Timestamp, taxonomy: pd.DataFrame) -> dict | None:
    """The store's most recent problem with no complaints since ``quiet_since``. The dataset has no fix log,
    so "solved" means the complaints stopped."""
    if store not in history.index.get_level_values("store"):
        return None
    quiet = history.loc[store]
    quiet = quiet[quiet["last_week"] <= quiet_since]
    if quiet.empty:
        return None
    type_id = quiet["last_report"].idxmax()
    return {
        "problem": str(taxonomy.loc[type_id, "issue_type"]),
        "last_report": f"{quiet.loc[type_id, 'last_report']:%Y-%m-%d}",
        "reports": int(quiet.loc[type_id, "reports"]),
    }


def store_map(
    analysis: Analysis,
    week: pd.Timestamp,
    taxonomy: pd.DataFrame,
    stores: pd.DataFrame,
    locations: pd.DataFrame,
    quiet_weeks: int,
) -> list[dict]:
    """One pin per store: this week's open problems, early warnings and the last problem that went quiet.

    Only weeks up to the picked one are used.
    """
    records = analysis.records
    action = records[(records["actionable"] == 1) & records["store"].notna() & (records["week_start"] <= week)]
    this_week = action[action["week_start"] == week]
    week_flags = analysis.flags[analysis.flags["as_of_week_start"] == week_label(week)]
    history = action.groupby(["store", "issue_type_id"]).agg(
        last_week=("week_start", "max"), last_report=("created_at", "max"), reports=("feedback_id", "size")
    )
    quiet_since = week - pd.Timedelta(weeks=quiet_weeks)

    pins = []
    # Stores without a location still get a pin (for the store board and store pages); the map skips them.
    for store in stores.merge(locations, on="store_id", how="left").itertuples(index=False):
        rows = this_week[this_week["store"] == store.store_id]
        warnings = week_flags.loc[week_flags["store_id"] == store.store_id, "issue_type_id"]
        pins.append(
            {
                "store_id": store.store_id,
                "name": store.store_name,
                "city": store.city,
                "region": store.region,
                "format": store.format,
                "lat": None if pd.isna(store.lat) else float(store.lat),
                "lon": None if pd.isna(store.lon) else float(store.lon),
                "cases": int(rows["incident_id"].nunique()),
                "urgent": int(rows.loc[rows["severity"].isin(URGENT), "incident_id"].nunique()),
                "worst": _worst(rows["severity"]) if len(rows) else None,
                "problems": _store_problems(rows, taxonomy),
                "warnings": [str(taxonomy.loc[t, "issue_type"]) for t in warnings],
                "last_solved": _last_solved(history, store.store_id, quiet_since, taxonomy),
            }
        )
    return pins
