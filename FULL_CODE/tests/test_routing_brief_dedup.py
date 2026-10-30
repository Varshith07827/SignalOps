import pandas as pd

from voice_of_store.brief import build_region_brief, render_markdown, trend_arrow
from voice_of_store.dedup import assign_incidents
from voice_of_store.routing import NOT_ROUTED, escalation_level, route_records, sla_hours

WEEK = pd.Timestamp("2026-09-21")


def test_escalation_rule_tiers():
    assert escalation_level("critical", emerging=False) == "Escalate to function head"
    assert escalation_level("low", emerging=True) == "Escalate to regional manager"
    assert escalation_level("high", emerging=False) == "Owner action"
    assert escalation_level("medium", emerging=False) == "Owner weekly queue"
    assert escalation_level("low", emerging=False) == "Weekly brief only"


def test_sla_hours_by_severity(settings):
    assert sla_hours("critical", settings.routing) == 24
    assert sla_hours("high", settings.routing) == 72
    assert sla_hours("low", settings.routing) is None


def test_only_actionable_records_are_routed(taxonomy, settings):
    records = pd.DataFrame({"issue_type_id": ["IT18", "IT18"], "severity": ["critical", "high"], "actionable": [1, 0]})
    routed = route_records(records, taxonomy, settings.routing)
    assert routed["owner_function"].tolist() == ["Merchandising", NOT_ROUTED]
    assert routed["escalation"].tolist() == ["Escalate to function head", NOT_ROUTED]


def test_trend_arrow_boundaries():
    assert trend_arrow(3, 0) == "NEW"
    assert trend_arrow(0, 0) == "="
    assert trend_arrow(13, 10) == "UP"
    assert trend_arrow(12, 10) == "="
    assert trend_arrow(7, 10) == "DOWN"


def _records() -> pd.DataFrame:
    base = WEEK + pd.Timedelta(hours=9)
    return pd.DataFrame(
        {
            "feedback_id": ["F1", "F2", "F3", "F4", "F5", "F6"],
            "store": ["ST-AAAAA", "ST-AAAAA", "ST-AAAAA", "ST-BBBBB", None, "ST-AAAAA"],
            "issue_type_id": ["IT10", "IT10", "IT10", "IT10", "IT26", "IT01"],
            "created_at": [
                base,
                base + pd.Timedelta(hours=30),
                base + pd.Timedelta(hours=100),
                base,
                base,
                base,
            ],
            "actionable": [1, 1, 1, 1, 1, 1],
        }
    )


def test_dedup_merges_same_store_issue_within_window_only(settings):
    incidents = assign_incidents(_records(), settings.dedup.window_hours)
    # F2 is 30 h after F1 (same incident); F3 is 100 h after (new incident); other store / no store stay apart.
    assert incidents.tolist() == ["F1", "F1", "F3", "F4", "F5", "F6"]


def test_brief_ranks_severe_issues_first_and_quotes_evidence(taxonomy, settings):
    records = _records().assign(
        week_start=WEEK,
        region="West",
        severity=["critical", "high", "high", "high", "low", "low"],
        issue_confidence=0.9,
        text=[
            "freezer broke, milk spoilt, kid fell ill",
            "frzr down",
            "chiller warm",
            "x",
            "app crash",
            "queue " * 80,
        ],
    )
    records["incident_id"] = assign_incidents(records, settings.dedup.window_hours)
    flags = pd.DataFrame(
        {"as_of_week_start": [WEEK.strftime("%Y-%m-%d")], "store_id": ["ST-AAAAA"], "issue_type_id": ["IT10"]}
    )
    names = {"ST-AAAAA": "Saffron Hyper Kothrud", "ST-BBBBB": "Saffron Express Vashi"}
    items = build_region_brief(records, flags, "West", WEEK, taxonomy, names, settings.brief)
    assert [item.issue_type_id for item in items] == ["IT10", "IT01", "IT26"]
    top = items[0]
    assert top.emerging and top.severity == "critical" and top.escalation == "Escalate to function head"
    assert top.incidents == 3 and top.reports == 4 and top.trend == "NEW"
    assert top.stores == ["Saffron Express Vashi", "Saffron Hyper Kothrud"]
    assert top.quotes[0] == "freezer broke, milk spoilt, kid fell ill"
    assert len(items[1].quotes[0]) == settings.brief.quote_max_chars
    markdown = render_markdown("West", WEEK, items)
    assert "EMERGING" in markdown and "Merchandising" not in markdown


def test_brief_for_quiet_region_says_so(taxonomy, settings):
    empty = _records().assign(week_start=WEEK, region="East", severity="low", issue_confidence=0.5, text="t")
    empty["incident_id"] = empty["feedback_id"]
    flags = pd.DataFrame(columns=["as_of_week_start", "store_id", "issue_type_id"])
    items = build_region_brief(empty, flags, "West", WEEK, taxonomy, {}, settings.brief)
    assert items == []
    assert "No actionable issues" in render_markdown("West", WEEK, items)
