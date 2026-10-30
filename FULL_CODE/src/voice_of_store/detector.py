"""Weekly early-warning detector. Week w only uses data from weeks up to w.

For each store and issue type we compare this week's count with the count we'd expect:
store volume x the store's usual share of that issue (shrunk toward the chain average for small stores)
x how much the same issue moved at all other stores (so chain-wide spikes don't flag one store).
The Poisson p-value of the observed count is the score. Safety-type issues get a lower bar, at most
max_flags_per_week flags are raised, and a flagged store/issue is not flagged again during the cooldown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import poisson

from voice_of_store.config import DetectorSettings

logger = logging.getLogger(__name__)

FLAG_COLUMNS = ["as_of_week_start", "store_id", "issue_type_id", "confidence", "evidence_feedback_ids"]


@dataclass(frozen=True)
class CountCube:
    """Weekly record counts: ``issue[s, t, w]`` per store and issue type, ``volume[s, w]`` all feedback per store."""

    stores: list[str]
    issue_types: list[str]
    weeks: list[pd.Timestamp]
    issue: np.ndarray
    volume: np.ndarray


def build_count_cube(
    labelled: pd.DataFrame, stores: list[str], issue_types: list[str], weeks: list[pd.Timestamp]
) -> CountCube:
    """Count records per (store, issue type, week). ``labelled`` needs store, issue_type_id and week_start."""
    store_idx = {s: i for i, s in enumerate(stores)}
    type_idx = {t: i for i, t in enumerate(issue_types)}
    week_idx = {w: i for i, w in enumerate(weeks)}
    rows = labelled[labelled["store"].isin(store_idx) & labelled["week_start"].isin(week_idx)]
    s = rows["store"].map(store_idx).to_numpy()
    w = rows["week_start"].map(week_idx).to_numpy()
    volume = np.zeros((len(stores), len(weeks)))
    np.add.at(volume, (s, w), 1)
    is_issue = rows["issue_type_id"].isin(type_idx).to_numpy()
    t = rows.loc[is_issue, "issue_type_id"].map(type_idx).to_numpy()
    issue = np.zeros((len(stores), len(issue_types), len(weeks)))
    np.add.at(issue, (s[is_issue], t, w[is_issue]), 1)
    return CountCube(stores, issue_types, weeks, issue, volume)


def window_surprise(cube: CountCube, week: int, window: int, settings: DetectorSettings) -> np.ndarray | None:
    """Poisson p-value of each cell's count over ``window`` weeks ending at ``week`` (None if too little history)."""
    start = week - window + 1
    base_end = start - settings.gap_weeks
    base_start = max(0, base_end - settings.history_weeks)
    if start < 0 or base_end - base_start < settings.min_history_weeks:
        return None
    prior = settings.prior_strength
    hist = cube.issue[:, :, base_start:base_end].sum(axis=2)
    hist_volume = cube.volume[:, base_start:base_end].sum(axis=1)
    chain_share = hist.sum(axis=0) / max(hist_volume.sum(), 1.0)
    store_share = (hist + prior * chain_share) / (hist_volume[:, None] + prior)

    observed = cube.issue[:, :, start : week + 1].sum(axis=2)
    volume = cube.volume[:, start : week + 1].sum(axis=1)
    # Rate at all other stores, shrunk toward history. Leaving the store out stops its own spike
    # from raising its own expected count.
    others_count = observed.sum(axis=0)[None, :] - observed
    others_volume = (volume.sum() - volume)[:, None]
    others_share = (others_count + prior * chain_share) / (others_volume + prior)
    chain_ratio = np.clip(
        others_share / np.maximum(chain_share[None, :], 1e-9),
        settings.chain_ratio_min,
        settings.chain_ratio_max,
    )
    expected = np.maximum(volume[:, None] * store_share * chain_ratio, 1e-3)
    return poisson.sf(observed - 1, expected)


def week_scores(cube: CountCube, week: int, policy_mask: np.ndarray, settings: DetectorSettings) -> np.ndarray:
    """Policy-weighted surprise per cell for one week (lower = more alarming); inf where not eligible."""
    p_values = [window_surprise(cube, week, w, settings) for w in settings.scan_windows]
    p_values = [p for p in p_values if p is not None]
    if not p_values:
        return np.full(cube.issue.shape[:2], np.inf)
    best = np.minimum.reduce(p_values)
    scores = best / np.where(policy_mask[None, :], settings.policy_weight, 1.0)
    min_count = np.where(policy_mask[None, :], settings.min_count_policy, settings.min_count_other)
    eligible = (cube.issue[:, :, week] >= min_count) & (scores < settings.p_value_threshold)
    return np.where(eligible, scores, np.inf)


def detect_flags(
    labelled: pd.DataFrame,
    stores: list[str],
    taxonomy: pd.DataFrame,
    weeks: list[pd.Timestamp],
    emit_weeks: set[pd.Timestamp],
    settings: DetectorSettings,
) -> pd.DataFrame:
    """Run the detector week by week over ``weeks`` and return the flags raised in ``emit_weeks``.

    Earlier weeks are always replayed (even when not emitted) because the cooldown depends on past flags.
    """
    issue_types = [t for t in taxonomy.index if str(taxonomy.loc[t, "is_actionable_category"]) == "1"]
    policy_mask = np.array([taxonomy.loc[t, "policy_severity_floor"] == "high" for t in issue_types])
    cube = build_count_cube(labelled, stores, issue_types, weeks)
    evidence = _evidence_index(labelled)
    last_flagged: dict[tuple[int, int], int] = {}
    flags = []
    for week in range(len(weeks)):
        scores = week_scores(cube, week, policy_mask, settings)
        raised = 0
        for s, t in sorted(zip(*np.nonzero(np.isfinite(scores)), strict=True), key=lambda c: scores[c]):
            previous = last_flagged.get((s, t))
            if previous is not None and week - previous <= settings.cooldown_weeks:
                # Still high: keep the existing flag open instead of spending budget on it again.
                last_flagged[(s, t)] = week
                continue
            if raised == settings.max_flags_per_week:
                break
            last_flagged[(s, t)] = week
            raised += 1
            if weeks[week] in emit_weeks:
                ids = evidence[(cube.stores[s], cube.issue_types[t], weeks[week])]
                flags.append(
                    {
                        "as_of_week_start": weeks[week].strftime("%Y-%m-%d"),
                        "store_id": cube.stores[s],
                        "issue_type_id": cube.issue_types[t],
                        "confidence": _confidence(scores[s, t]),
                        "evidence_feedback_ids": ";".join(ids),
                    }
                )
    logger.info("Detector raised %d flags in %d emitted weeks", len(flags), len(emit_weeks))
    return pd.DataFrame(flags, columns=FLAG_COLUMNS)


def _evidence_index(labelled: pd.DataFrame) -> dict[tuple[str, str, pd.Timestamp], list[str]]:
    """Feedback ids per (store, issue type, week), most confident classifications first."""
    rows = labelled.dropna(subset=["store"]).sort_values(["issue_confidence", "feedback_id"], ascending=[False, True])
    grouped = rows.groupby(["store", "issue_type_id", "week_start"], sort=False)["feedback_id"]
    return {key: list(ids) for key, ids in grouped}


def _confidence(score: float) -> float:
    """Reported (not scored) confidence: 1e-4 maps to 0.4, 1e-10 and below to 1.0."""
    return round(float(min(1.0, -np.log10(max(score, 1e-300)) / 10.0)), 3)
