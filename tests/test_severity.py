import json

import pandas as pd

from src import preprocessing as pp
from src.prioritization import build_cases
from src.routing import TRIAGE_OWNER, assign_owner, recommended_action
from src.severity import PolicyEngine

ENGINE = PolicyEngine()


def assess(text, category, decision="auto"):
    return ENGINE.assess(pp.enrich_text(pp.normalise_text(text)), category, decision)


def test_single_allergen_report_is_critical_and_escalated():
    r = assess("Label says nut-free but lists peanut traces, my son had a reaction", "allergen_labelling")
    assert r["policy_severity"] == "Critical"
    assert r["mandatory_escalation"]
    assert "POL-ALLERGEN" in r["policy_rules"]
    assert r["policy_escalation"] == "Mandatory escalation (24h)"
    assert r["verification_status"] == "Allegation (unverified)"  # high severity != verified


def test_allergen_terms_escalate_even_if_misclassified():
    r = assess("my daughter had an allergic reaction to these biscuits", "product_quality")
    assert r["policy_severity"] == "Critical"
    assert "POL-ALLERGEN" in r["policy_rules"]


def test_safety_escalation_even_when_unclassified():
    r = assess("cockroach in the packet", "unclassified", decision="unknown")
    assert r["mandatory_escalation"] and r["policy_severity"] in ("High", "Critical")


def test_hygiene_and_misconduct_policy_levels():
    assert assess("store was filthy and unhygienic", "hygiene_cleanliness")["policy_severity"] == "High"
    assert assess("the cashier was rude", "staff_misconduct")["policy_severity"] == "High"
    assert assess("an employee was harassing a female customer", "staff_misconduct")["policy_severity"] == "Critical"
    assert assess("slipped on oil and hurt my back", "physical_safety_hazard")["policy_severity"] == "Critical"


def test_gluten_free_range_request_is_not_an_allergen_escalation(classifier):
    text = "Why doesn't this store carry gluten-free bread? Other branches have it."
    pred = classifier.predict_frame([text]).iloc[0]
    r = assess(text, pred["pred_category"], pred["decision"])
    assert pred["candidate_category"] != "allergen_labelling"
    assert not r["mandatory_escalation"]


def test_non_policy_issue_not_escalated():
    r = assess("queue was 30 minutes long", "queue_management")
    assert r["policy_severity"] == "Low" and not r["mandatory_escalation"]
    assert r["policy_escalation"] == "Monitor"


def test_negated_safety_mention_does_not_escalate():
    r = assess("Very clean store, no rats or cockroaches unlike others", "no_issue")
    assert not r["mandatory_escalation"]
    assert not r["requires_action"]


def test_owner_assignment():
    assert assign_owner("refrigeration_failure")[0] == "Store Ops"
    assert assign_owner("payment_failure")[0] == "Digital"
    assert assign_owner("stock_shortage")[0] == "Supply Chain"
    assert assign_owner("staff_misconduct")[0] == "HR"
    assert assign_owner("allergen_labelling")[0] == "Merchandising"
    assert assign_owner("unclassified")[0] == TRIAGE_OWNER
    action = recommended_action("allergen_labelling", "Policy", "Critical", True)
    assert "24h" in action and "confirmed" in action


def _processed_row(fid, store, cat, text, ts, severity_fields):
    return {"feedback_id": fid, "store_id": store, "pred_category": cat, "original_text": text,
            "timestamp": pd.Timestamp(ts), "channel": "call_centre", "confidence": 0.9,
            "cluster_id": f"CL-{fid}", **severity_fields}


def test_single_report_creates_p1_case_regardless_of_volume():
    stores = pd.DataFrame([{"store_id": "S1", "store_name": "Test Store", "region": "North"}])
    text = "label says nut free but has peanut, allergic reaction"
    sev = ENGINE.assess(pp.enrich_text(pp.normalise_text(text)), "allergen_labelling", "auto")
    rows = [_processed_row("F1", "S1", "allergen_labelling", text, "2026-09-27 10:00", sev)]
    # plus ordinary low-severity noise with higher volume
    noise = ENGINE.assess("long queue", "queue_management", "auto")
    rows += [_processed_row(f"N{i}", "S1", "queue_management", "long queue", "2026-09-26 10:00", noise)
             for i in range(20)]
    processed = pd.DataFrame(rows)
    cases = build_cases(processed, stores, pd.DataFrame(), None, as_of="2026-09-27")
    assert len(cases) == 1
    case = cases.iloc[0]
    assert case["tier"] == 1 and case["severity"] == "Critical"
    assert json.loads(case["evidence_ids"]) == ["F1"]
    assert "regardless of volume" in case["explanation"]
    assert "P3" not in case["explanation"] and "P2" not in case["explanation"]
