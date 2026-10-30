import pandas as pd
import pytest

from voice_of_store.data_io import DataValidationError, validate_feedback, validate_labels, week_start_of


def _feedback(**overrides) -> pd.DataFrame:
    base = {
        "feedback_id": ["FB-1", "FB-2"],
        "channel": ["in_app", "staff_shift_note"],
        "created_at": ["2026-07-15T10:00:00", "2026-07-19T23:59:59"],
        "store_id": ["", "st-abcde"],
        "rating": ["4", ""],
        "text": ["ok", "frzr down"],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_valid_feedback_gets_monday_week_and_clean_store():
    frame = validate_feedback(_feedback())
    assert frame["week_start"].dt.strftime("%Y-%m-%d").tolist() == ["2026-07-13", "2026-07-13"]
    assert frame["store_id"].isna().tolist() == [True, False]
    assert frame.loc[1, "store_id"] == "ST-ABCDE"
    assert frame["rating"].isna().tolist() == [False, True]


@pytest.mark.parametrize(
    "overrides",
    [
        {"feedback_id": ["FB-1", "FB-1"]},
        {"channel": ["in_app", "fax"]},
        {"created_at": ["2026-07-15T10:00:00", "not a date"]},
        {"rating": ["4", "9"]},
    ],
)
def test_invalid_feedback_is_rejected(overrides):
    with pytest.raises(DataValidationError):
        validate_feedback(_feedback(**overrides))


def test_labels_out_of_range_are_rejected():
    labels = pd.DataFrame(
        {"feedback_id": ["FB-1"], "issue_type_id": ["IT31"], "severity": ["low"], "actionable": ["1"]}
    )
    with pytest.raises(DataValidationError):
        validate_labels(labels)


def test_sunday_belongs_to_the_week_that_started_monday():
    stamps = pd.Series(pd.to_datetime(["2026-07-19 23:59:59", "2026-07-20 00:00:00"]))
    assert week_start_of(stamps).dt.strftime("%Y-%m-%d").tolist() == ["2026-07-13", "2026-07-20"]
