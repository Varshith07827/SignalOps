import pandas as pd
import pytest

from voice_of_store.commands import (
    build_command,
    compare_with_submission,
    detector_command,
    display,
    run_command,
    weeks_between,
)
from voice_of_store.config import FULL_CODE_DIR
from voice_of_store.reports import DETECTOR_COMMAND

WEEKS = list(pd.date_range("2026-03-30", periods=6, freq="7D"))


def test_detector_command_matches_the_submitted_template(settings):
    out = FULL_CODE_DIR / "outputs" / "runs" / "x" / "week.csv"
    command = detector_command(settings, pd.Timestamp("2026-07-13"), out)
    expected = DETECTOR_COMMAND.strip().format(
        feedback="FULL_CODE/data/feedback.csv", asof="2026-07-13", out="FULL_CODE/outputs/runs/x/week.csv"
    )
    assert display(command) == expected


def test_build_command_optionally_adds_cross_validation():
    assert build_command(False) == ["python", "FULL_CODE/main.py"]
    assert build_command(True) == ["python", "FULL_CODE/main.py", "--cv"]


def test_weeks_between_is_inclusive_and_validated():
    assert weeks_between(WEEKS, WEEKS[1], WEEKS[3]) == WEEKS[1:4]
    assert weeks_between(WEEKS, WEEKS[2], WEEKS[2]) == [WEEKS[2]]
    with pytest.raises(ValueError):
        weeks_between(WEEKS, WEEKS[3], WEEKS[1])
    with pytest.raises(ValueError):
        weeks_between(WEEKS, pd.Timestamp("2026-04-01"), WEEKS[2])  # a Wednesday, not a calendar week


def test_run_command_reports_exit_code_and_output():
    result = run_command(["python", "-c", "print('hello'); raise SystemExit(3)"], timeout_seconds=60)
    assert result.returncode == 3 and not result.ok
    assert "hello" in result.output


def test_run_command_stops_at_timeout():
    result = run_command(["python", "-c", "import time; time.sleep(30)"], timeout_seconds=1)
    assert result.returncode == -1
    assert "Stopped" in result.output


def test_compare_with_submission_flags_differences():
    row = {
        "as_of_week_start": "2026-03-30",
        "store_id": "ST-A",
        "issue_type_id": "IT10",
        "confidence": 0.5,
        "evidence_feedback_ids": "FB-1;FB-2",
    }
    submitted = pd.DataFrame([row])
    same = {WEEKS[0]: pd.DataFrame([row]), WEEKS[1]: pd.DataFrame(columns=submitted.columns)}
    result = compare_with_submission(same, submitted)
    assert result["identical"].tolist() == [True, True]
    changed = {WEEKS[0]: pd.DataFrame([{**row, "store_id": "ST-B"}])}
    assert compare_with_submission(changed, submitted)["identical"].tolist() == [False]
