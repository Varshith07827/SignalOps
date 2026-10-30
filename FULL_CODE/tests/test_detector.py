from dataclasses import replace

import pandas as pd
import pytest

from voice_of_store.detector import FLAG_COLUMNS, detect_flags

WEEKS = list(pd.date_range("2026-01-05", periods=12, freq="7D"))
STORES = ["ST-A", "ST-B", "ST-C", "ST-D"]
BACKGROUND = {"NI01": 20, "IT14": 2, "IT26": 1}


def _records(extra: list[tuple[str, str, int, int]]) -> pd.DataFrame:
    """Steady background at every store plus ``extra`` (store, issue type, week index, count) records."""
    rows = []
    cells = [(s, t, w, n) for s in STORES for w in range(len(WEEKS)) for t, n in BACKGROUND.items()] + extra
    for store, issue_type, week, count in cells:
        for k in range(count):
            rows.append(
                {
                    "feedback_id": f"FB-{store}-{issue_type}-{week}-{k}-{len(rows)}",
                    "store": store,
                    "issue_type_id": issue_type,
                    "week_start": WEEKS[week],
                    "created_at": WEEKS[week] + pd.Timedelta(hours=10 + k),
                    "issue_confidence": 0.9,
                }
            )
    return pd.DataFrame(rows)


def _flags(records, taxonomy, settings, emit=None):
    emit_weeks = set(WEEKS) if emit is None else emit
    return detect_flags(records, STORES, taxonomy, WEEKS, emit_weeks, settings.detector)


def test_small_policy_spike_at_one_store_is_flagged_with_its_evidence(taxonomy, settings):
    records = _records([("ST-A", "IT10", 8, 3)])
    flags = _flags(records, taxonomy, settings)
    assert list(flags.columns) == FLAG_COLUMNS
    assert flags[["as_of_week_start", "store_id", "issue_type_id"]].values.tolist() == [
        [WEEKS[8].strftime("%Y-%m-%d"), "ST-A", "IT10"]
    ]
    evidence = flags.loc[0, "evidence_feedback_ids"].split(";")
    expected = records[(records["store"] == "ST-A") & (records["issue_type_id"] == "IT10")]["feedback_id"]
    assert sorted(evidence) == sorted(expected)
    assert 0.0 <= flags.loc[0, "confidence"] <= 1.0


def test_chain_wide_rise_is_not_a_store_problem(taxonomy, settings):
    outage = [(store, "IT26", 8, 7) for store in STORES]
    assert _flags(_records(outage), taxonomy, settings).empty


def test_non_policy_issue_needs_three_records(taxonomy, settings):
    assert _flags(_records([("ST-A", "IT01", 8, 2)]), taxonomy, settings).empty
    assert len(_flags(_records([("ST-A", "IT01", 8, 4)]), taxonomy, settings)) == 1


def test_open_escalation_is_not_re_raised_during_cooldown(taxonomy, settings):
    records = _records([("ST-A", "IT10", 8, 3), ("ST-A", "IT10", 9, 5), ("ST-A", "IT10", 10, 6)])
    flags = _flags(records, taxonomy, settings)
    assert flags["as_of_week_start"].tolist() == [WEEKS[8].strftime("%Y-%m-%d")]


def test_weekly_flag_budget_is_respected(taxonomy, settings):
    spikes = [(store, issue, 8, 4) for store in STORES for issue in ("IT10", "IT17")]
    flags = _flags(_records(spikes), taxonomy, settings)
    assert len(flags) == settings.detector.max_flags_per_week


def test_flags_ignore_future_weeks(taxonomy, settings):
    week = {WEEKS[8]}
    base = _records([("ST-A", "IT10", 8, 3)])
    with_future = _records([("ST-A", "IT10", 8, 3), ("ST-B", "IT18", 10, 9), ("ST-A", "IT10", 11, 9)])
    pd.testing.assert_frame_equal(_flags(base, taxonomy, settings, week), _flags(with_future, taxonomy, settings, week))


def test_too_little_history_raises_nothing(taxonomy, settings):
    assert _flags(_records([("ST-A", "IT10", 1, 5)]), taxonomy, settings).empty


@pytest.mark.parametrize("threshold, expected", [(1e-12, 0), (1e-4, 1)])
def test_threshold_controls_sensitivity(taxonomy, settings, threshold, expected):
    tuned = replace(settings, detector=replace(settings.detector, p_value_threshold=threshold))
    assert len(_flags(_records([("ST-A", "IT10", 8, 3)]), taxonomy, tuned)) == expected
