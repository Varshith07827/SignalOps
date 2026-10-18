import numpy as np
import pandas as pd

from src import anomaly_detection as ad

STORES = [f"S{i:02d}" for i in range(30)]
CATS = ["refrigeration_failure", "payment_failure", "stock_shortage", "parking_access", "no_issue"]


def cube_from(counts: np.ndarray) -> ad.CountCube:
    days = pd.date_range("2026-01-01", periods=counts.shape[2], freq="D")
    return ad.CountCube(counts.astype(np.int32), counts.astype(np.int32), STORES, CATS, days)


def background(seed=0, days=140, base=(0.1, 0.15, 0.6, 0.03, 1.0)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    lam = np.array(base)[None, :, None] * np.ones((len(STORES), len(CATS), days))
    lam[0, 2, :] *= 6  # chronic high-volume cell (negative control)
    return rng.poisson(lam)


def test_benjamini_hochberg_matches_definition():
    p = np.array([0.01, 0.04, 0.03, 0.5])
    q = ad.benjamini_hochberg(p)
    # sorted p: .01,.03,.04,.5 -> p*n/rank: .04,.06,.0533,.5 -> running min from the top
    assert np.allclose(q, [0.04, 0.16 / 3, 0.16 / 3, 0.5])


def test_ordinary_fluctuations_not_flagged():
    flags = 0
    for seed in range(5):
        cube = cube_from(background(seed))
        res = ad.detect_at(cube, 139)
        flags += int(res["flagged"].sum())
    assert flags <= 1


def test_chronic_high_volume_cell_not_flagged_despite_largest_total():
    cube = cube_from(background(1))
    res = ad.detect_at(cube, 139)
    top = res.sort_values("current_count", ascending=False).iloc[0]
    assert (top["store_id"], top["category"]) == ("S00", "stock_shortage")
    assert not top["flagged"]


def test_store_level_spike_is_flagged_with_explanation_fields():
    counts = background(2)
    counts[5, 0, 126:140] += np.array([0, 1, 0, 1, 1, 0, 1, 1, 1, 0, 2, 1, 1, 2])  # refrigeration ramps up
    res = ad.detect_at(cube_from(counts), 139)
    row = res[(res.store_id == "S05") & (res.category == "refrigeration_failure")].iloc[0]
    assert row["flagged"]
    for col in ("baseline_weekly_mean", "expected_count", "p_value", "q_value", "rate_ratio", "network_ratio"):
        assert np.isfinite(row[col])


def test_one_to_three_rise_is_not_flagged_and_ranks_below_credible_problem():
    counts = background(3)
    counts[7, 3, :] = 0
    counts[7, 3, 0:133:7] = 1  # parking: exactly 1 report per week historically
    counts[7, 3, [134, 136, 138]] = 1  # ... then 3 in the current week ("1 -> 3")
    counts[8, 1, 126:140] += 2  # sustained payment problem elsewhere
    res = ad.detect_at(cube_from(counts), 139)
    small = res[(res.store_id == "S07") & (res.category == "parking_access")].iloc[0]
    big = res[(res.store_id == "S08") & (res.category == "payment_failure")].iloc[0]
    assert small["rate_ratio"] >= 2  # large percentage growth...
    assert not small["flagged"]  # ...is not enough on its own
    assert big["flagged"] and big["p_value"] < small["p_value"]


def test_rare_category_surge_is_flagged_but_ranks_below_credible_problem():
    counts = background(3)
    counts[7, 3, 133:140] = 0
    counts[7, 3, [134, 136, 138]] = 1  # ~0.2/week historically -> 3 in a week
    counts[8, 1, 126:140] += 2
    res = ad.detect_at(cube_from(counts), 139)
    small = res[(res.store_id == "S07") & (res.category == "parking_access")].iloc[0]
    big = res[(res.store_id == "S08") & (res.category == "payment_failure")].iloc[0]
    assert small["flagged"]  # low-volume issues matter when they rise unusually quickly
    assert big["p_value"] < small["p_value"] and big["z_score"] > small["z_score"] * 0.5


def test_network_wide_rise_is_not_a_store_level_anomaly():
    counts = background(4)
    rng = np.random.default_rng(9)
    counts[:, 1, 126:140] += rng.poisson(0.5, size=(len(STORES), 14))  # all stores rise together
    res = ad.detect_at(cube_from(counts), 139)
    assert res[res.category == "payment_failure"]["flagged"].sum() <= 1


def test_no_look_ahead():
    counts = background(5)
    cube = cube_from(counts)
    before = ad.detect_at(cube, 120)
    future = counts.copy()
    future[:, :, 121:] += 25  # a huge future change must not alter an earlier as-of result
    after = ad.detect_at(cube_from(future), 120)
    pd.testing.assert_frame_equal(before, after)


def test_insufficient_history_returns_none():
    assert ad.detect_at(cube_from(background(6, days=40)), 39) is None


def _signal(pipeline_output, key):
    sc = pipeline_output["manifest"]["scenarios"][key]
    sig = pipeline_output["signals"]
    hit = sig[(sig.store_id == sc["store_id"]) & (sig.category == sc["category"]) & sig.flagged]
    return sc, hit


def test_planted_refrigeration_incident_detected_and_routed(pipeline_output):
    sc, hit = _signal(pipeline_output, "A")
    assert len(hit) == 1
    row = hit.iloc[0]
    assert row["owner"] == "Store Ops"
    assert row["n_channels"] >= 3
    assert row["evidence_ids"], "supporting feedback must be preserved"
    assert "EMERGING" in row["explanation"]


def test_planted_payment_incident_detected_and_routed(pipeline_output):
    sc, hit = _signal(pipeline_output, "C")
    assert len(hit) == 1
    assert hit.iloc[0]["owner"] == "Digital"


def test_planted_trends_found_in_rolling_replay_without_lookahead(pipeline_output):
    p, stores = pipeline_output["processed"], pipeline_output["stores"]
    for key in ("A", "C"):
        sc = pipeline_output["manifest"]["scenarios"][key]
        roll = ad.rolling_detection(p, stores, start=pd.Timestamp(sc["onset"]).normalize())
        hit = roll[(roll.store_id == sc["store_id"]) & (roll.category == sc["category"]) & roll.flagged]
        assert len(hit) > 0
        assert pd.to_datetime(hit["as_of"]).min() >= pd.Timestamp(sc["onset"])
