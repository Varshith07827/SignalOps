import pandas as pd

from src import preprocessing as pp
from src.deduplication import deduplicate, summary
from tests.conftest import make_records


def rec(fid, store, cat, ts, text):
    norm = pp.normalise_text(text)
    return {"feedback_id": fid, "store_id": store, "pred_category": cat, "timestamp": ts,
            "normalised_text": norm, "entities": sorted(pp.extract_entities(norm))}


def run(rows):
    df = make_records(rows)
    return pd.concat([df, deduplicate(df)], axis=1)


def test_duplicate_candidates_are_merged():
    out = run([
        rec("a", "S1", "refrigeration_failure", "2026-09-01 10:00", "dairy chiller not cold, milk warm"),
        rec("b", "S1", "refrigeration_failure", "2026-09-01 11:30", "the dairy chiller is not cooling, milk was warm"),
    ])
    assert out["cluster_id"].nunique() == 1
    assert out.loc[1, "dup_status"] == "merged duplicate"
    assert out["is_cluster_anchor"].tolist() == [True, False]


def test_different_store_never_merged():
    out = run([
        rec("a", "S1", "refrigeration_failure", "2026-09-01 10:00", "dairy chiller not cold, milk warm"),
        rec("b", "S2", "refrigeration_failure", "2026-09-01 10:05", "dairy chiller not cold, milk warm"),
    ])
    assert out["cluster_id"].nunique() == 2


def test_same_category_far_apart_not_merged():
    out = run([
        rec("a", "S1", "payment_failure", "2026-09-01 10:00", "UPI payment failed at counter 3"),
        rec("b", "S1", "payment_failure", "2026-09-04 10:00", "UPI payment failed at counter 3"),
    ])
    assert out["cluster_id"].nunique() == 2


def test_same_category_unrelated_reports_not_silently_merged():
    out = run([
        rec("a", "S1", "stock_shortage", "2026-09-01 09:00", "atta out of stock again"),
        rec("b", "S1", "stock_shortage", "2026-09-01 20:00", "no diapers in the baby care aisle, shelf empty"),
    ])
    assert out["cluster_id"].nunique() == 2
    assert (out["dup_status"] != "merged duplicate").all()


def test_uncertain_match_flagged_as_possible_duplicate():
    out = run([
        rec("a", "S1", "payment_failure", "2026-09-01 10:00", "card declined at billing counter"),
        rec("b", "S1", "payment_failure", "2026-09-01 18:00", "my card was declined at the counter"),
    ])
    assert out["cluster_id"].nunique() == 2
    assert out.loc[1, "dup_status"] == "possible duplicate"
    assert out.loc[1, "possible_duplicate_of"] == out.loc[0, "cluster_id"]


def test_no_chaining_beyond_anchor_window():
    base = pd.Timestamp("2026-09-01 08:00")
    rows = [rec(f"r{i}", "S1", "refrigeration_failure", str(base + pd.Timedelta(hours=10 * i)),
                "dairy chiller not cooling milk warm") for i in range(8)]  # identical wording, every 10h
    out = run(rows)
    assert len(out) == 8  # every original record preserved
    assert out["cluster_id"].nunique() >= 2  # a 70h run cannot collapse into one incident
    spans = out.groupby("cluster_id")["timestamp"].agg(lambda t: (t.max() - t.min()).total_seconds() / 3600)
    assert (spans <= 36).all()  # no cluster extends beyond the anchor window


def test_unclassified_records_stay_separate_and_summary():
    out = run([
        rec("a", "S1", "unclassified", "2026-09-01 10:00", "hello"),
        rec("b", "S1", "unclassified", "2026-09-01 10:01", "hello"),
    ])
    assert out["cluster_id"].nunique() == 2
    s = summary(out)
    assert s["total_records"] == 2 and s["estimated_unique_incidents"] == 2


def test_pipeline_dedup_reduces_incidents_but_keeps_records(pipeline_output):
    p = pipeline_output["processed"]
    assert len(p) == 12_000
    assert p["cluster_id"].nunique() < len(p)
    assert p["feedback_id"].is_unique
