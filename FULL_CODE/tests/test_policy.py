import pandas as pd

from voice_of_store.policy import apply_severity_floor, can_be_actionable


def test_severity_never_below_policy_floor(taxonomy):
    predicted = pd.Series(["low", "low", "critical", "medium"])
    types = pd.Series(["IT18", "IT01", "IT01", "IT27"])
    result = apply_severity_floor(predicted, types, taxonomy)
    assert result.tolist() == ["high", "low", "critical", "medium"]


def test_failed_payment_is_at_least_medium(taxonomy):
    result = apply_severity_floor(pd.Series(["low"]), pd.Series(["IT27"]), taxonomy)
    assert result.tolist() == ["medium"]


def test_unknown_issue_type_defaults_to_low_floor(taxonomy):
    result = apply_severity_floor(pd.Series(["low"]), pd.Series(["XX99"]), taxonomy)
    assert result.tolist() == ["low"]


def test_actionable_needs_real_issue_and_routable_owner():
    types = pd.Series(["IT10", "IT10", "IT26", "NI01", "IT23", "IT30"])
    store_known = pd.Series([True, False, False, True, False, False])
    assert can_be_actionable(types, store_known).tolist() == [True, False, True, False, True, False]


def test_storeless_routable_range_is_it23_to_it29():
    types = pd.Series(["IT22", "IT23", "IT29", "IT30"])
    store_known = pd.Series([False] * 4)
    assert can_be_actionable(types, store_known).tolist() == [False, True, True, False]
