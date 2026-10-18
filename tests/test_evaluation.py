import pandas as pd
import pytest

import config
from src import evaluation, reporting, storage


def test_escalation_precision_formula():
    assert evaluation.escalation_precision(8, 10) == pytest.approx(0.8)
    assert evaluation.escalation_precision(0, 0) is None


def test_record_level_escalation_precision_on_toy_data():
    df = pd.DataFrame({
        "feedback_id": list("abcde"),
        "mandatory_escalation": [True, True, True, False, False],
        "true_actionable": [True, True, False, True, False],
        "true_severity": ["Critical", "Medium", "Low", "High", "Low"],
        "true_issue_category": ["allergen_labelling", "billing_error", "no_issue", "hygiene_cleanliness", "no_issue"],
        "policy_severity": ["Critical", "High", "High", "Low", "Low"],
    })
    res = evaluation.evaluate_escalation(df, pd.DataFrame(columns=["case_id", "case_type", "tier", "evidence_ids",
                                                                   "store_id", "category"]),
                                         {"scenarios": {}})
    assert res["record_level"]["escalations"] == 3
    assert res["record_level"]["true_actionable_escalations"] == 1
    assert res["record_level"]["escalation_precision"] == pytest.approx(1 / 3, abs=1e-4)


def test_dedup_metrics_on_toy_groups():
    df = pd.DataFrame({
        "feedback_id": list("abcde"),
        "cluster_id": ["c1", "c1", "c2", "c3", "c3"],
        "incident_id": ["i1", "i1", "i1", "i2", "i3"],
        "dup_status": ["unique"] * 5, "is_cluster_anchor": [True, False, True, True, False],
        "possible_duplicate_of": [""] * 5,
    })
    res = evaluation.evaluate_dedup(df)
    # predicted pairs {ab, de}; true pairs {ab, ac, bc}
    assert res["pairwise_precision"] == pytest.approx(0.5)
    assert res["pairwise_recall"] == pytest.approx(1 / 3, abs=1e-4)


def test_classification_metrics_are_incident_level(pipeline_output):
    res = evaluation.evaluate_classification(pipeline_output["joined"])
    inc = res["incident_level_all"]
    assert inc["n"] == pipeline_output["joined"].query("true_issue_category != 'other'")["incident_id"].nunique()
    assert 0 < inc["macro_f1"] <= 1
    # hold-out phrasings are harder than training phrasings: evidence the split is real
    assert res["incident_level_holdout_templates"]["macro_f1"] < res["incident_level_train_templates"]["macro_f1"]
    assert len(res["confusion_matrix"]["matrix"]) == len(res["confusion_matrix"]["rows_true"])


def test_scenario_checks_pass_on_small_pipeline(pipeline_output):
    po = pipeline_output
    sig = po["signals"]
    checks = evaluation.check_scenarios(po["joined"], po["cases"].assign(
        evidence_ids=po["cases"]["evidence_ids"]), sig, po["manifest"])
    failed = [c for c in checks if not c["passed"]]
    assert not failed, failed


def test_regional_brief(pipeline_output):
    po = pipeline_output
    region = po["manifest"]["scenarios"]["A"]["region"]
    brief = reporting.build_regional_brief(po["processed"], po["cases"], po["signals"], region)
    assert brief["region"] == region
    assert 1 <= len(brief["top_issues"]) <= 5
    for issue in brief["top_issues"]:
        assert issue["quotes"] and issue["owner"] and issue["recommended_action"] and issue["severity"]
        assert "store_incidents_previous_week" in issue
    assert any(e["category"] == "Refrigeration failure" for e in brief["emerging"])
    html = reporting.render_brief_html(brief)
    assert "<html" in html and "synthetic" in html.lower()
    csv = reporting.brief_to_csv(brief)
    assert csv.lstrip("\ufeff").splitlines()[0].startswith("region,week,rank")


def test_case_status_persistence(tmp_path):
    db = tmp_path / "state.duckdb"
    storage.update_case("CASE-1", status="Under Review", owner="Store Ops", note="checking CCTV", path=db)
    storage.update_case("CASE-1", status="Assigned", verification="Under investigation", path=db)
    states = storage.get_case_states(path=db)  # fresh connection = survives restart
    row = states.set_index("case_id").loc["CASE-1"]
    assert row["status"] == "Assigned" and row["owner"] == "Store Ops"
    assert row["verification"] == "Under investigation"
    hist = storage.case_history("CASE-1", path=db)
    assert {"status", "owner", "verification"} <= set(hist["field"])
    with pytest.raises(ValueError):
        storage.update_case("CASE-1", status="Closed?", path=db)


def test_verification_states_distinguish_allegation_from_verified():
    assert config.VERIFICATION_STATES[0].startswith("Allegation")
    assert "Under investigation" in config.VERIFICATION_STATES
    assert "Verified incident" in config.VERIFICATION_STATES
