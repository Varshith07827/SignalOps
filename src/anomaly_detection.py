"""Store x issue-category emerging-issue detection.

Method (transparent, count-based)
---------------------------------
For an as-of day ``T`` and every (store, category) cell:

* **Unit of evidence** - estimated unique incidents (deduplicated cluster
  anchors), so one incident reported five times counts once. Records flagged as
  *possible duplicates* are not counted as independent new incidents.
* **Current window**  - incidents in the 7 days ending at ``T``.
* **Baseline**        - weekly counts over the previous 12 weeks (strictly before
  the current window; no look-ahead).
* **Empirical-Bayes baseline** - the store's own history is shrunk towards a
  prior equal to the category's network share times the store's overall weekly
  feedback volume (store size / exposure). This stops a zero history from
  making any single report look anomalous:
  ``lambda_base = (H + m * lambda_prior) / (B + m)``.
* **Exposure ratio**  - change in the store's volume of *other* categories
  (captures reporting-volume shifts, e.g. a new channel), clipped.
* **Network ratio**   - leave-one-out change of the category across all other
  stores (captures seasonality and network-wide events), clipped. The detector
  therefore asks: *is this store rising faster than its own history and the
  rest of the network?*
* **Expected count**  ``lambda = lambda_base * exposure_ratio * network_ratio``.
* **Statistical test** - one-sided negative-binomial tail probability
  ``P(X >= observed)`` with category-level over-dispersion estimated from the
  baseline (Poisson when no over-dispersion).
* **Multiple testing** - Benjamini-Hochberg q-values across all cells for the
  as-of day; the FDR level is stricter for low-severity categories.
* **Minimum evidence** - at least ``min_current_count`` incidents, an absolute
  increase of at least ``min_absolute_increase`` and a rate ratio of at least
  ``min_rate_ratio``. Percentage growth alone never raises a flag.

Cells that are notable but not confirmed (raw p <= ``watch_p_value``) are
labelled *Watch* and are not escalated.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

import config
from src import routing
from src.taxonomy import CATEGORY_BY_CODE, NO_ISSUE, OPERATIONAL_CODES, category_label


@dataclass
class CountCube:
    counts: np.ndarray  # stores x categories x days: unique incidents (cluster anchors)
    reports: np.ndarray  # stores x categories x days: raw reports
    store_ids: list[str]
    categories: list[str]
    days: pd.DatetimeIndex

    def day_index(self, as_of) -> int:
        d = pd.Timestamp(as_of).normalize()
        idx = int(self.days.get_indexer([d])[0])
        if idx < 0:
            raise ValueError(f"as_of {as_of} outside data range {self.days[0].date()}..{self.days[-1].date()}")
        return idx


def build_cube(df: pd.DataFrame, store_ids: list[str], categories: list[str] | None = None,
               start=None, end=None) -> CountCube:
    """Aggregate processed records into a daily (store, category) count cube."""
    categories = categories or [c for c in OPERATIONAL_CODES]
    start = pd.Timestamp(start or df["timestamp"].min()).normalize()
    end = pd.Timestamp(end or df["timestamp"].max()).normalize()
    days = pd.date_range(start, end, freq="D")
    s_map = {s: i for i, s in enumerate(store_ids)}
    c_map = {c: i for i, c in enumerate(categories)}
    shape = (len(store_ids), len(categories), len(days))
    counts = np.zeros(shape, dtype=np.int32)
    reports = np.zeros(shape, dtype=np.int32)
    sub = df[df["pred_category"].isin(c_map) & df["store_id"].isin(s_map)]
    sub = sub[(sub["timestamp"] >= start) & (sub["timestamp"] < end + pd.Timedelta(days=1))]
    si = sub["store_id"].map(s_map).to_numpy()
    ci = sub["pred_category"].map(c_map).to_numpy()
    di = ((sub["timestamp"].dt.normalize() - start).dt.days).to_numpy()
    np.add.at(reports, (si, ci, di), 1)
    # Possible duplicates are not merged for display, but they are not counted as
    # independent new incidents either (conservative evidence counting).
    anchor = (sub["is_cluster_anchor"] & (sub["dup_status"] != "possible duplicate")).to_numpy()
    np.add.at(counts, (si[anchor], ci[anchor], di[anchor]), 1)
    return CountCube(counts, reports, list(store_ids), list(categories), days)


def benjamini_hochberg(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    n = p.size
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(q, 1.0)
    return out


def _tail_probability(observed: np.ndarray, expected: np.ndarray, dispersion: np.ndarray) -> np.ndarray:
    """P(X >= observed) under NB(mean=expected, var=expected*dispersion)."""
    k = observed - 1
    poisson = stats.poisson.sf(k, expected)
    over = dispersion > 1.0001
    n = np.where(over, expected / np.maximum(dispersion - 1, 1e-9), 1.0)
    p_nb = np.where(over, 1.0 / dispersion, 0.5)
    nb = stats.nbinom.sf(k, n, p_nb)
    return np.where(observed <= 0, 1.0, np.where(over, nb, poisson))


def _window_stats(cube: CountCube, day_idx: int, w: int, settings: config.DetectionSettings) -> dict | None:
    """Expected vs observed for a ``w``-day window ending on ``day_idx``."""
    cnt = cube.counts
    cur_lo = day_idx - w + 1
    B = min(settings.baseline_weeks, cur_lo // 7) if cur_lo >= 0 else 0
    if B < settings.min_baseline_weeks:
        return None
    base_lo = cur_lo - 7 * B
    scale = w / 7.0
    cur = cnt[:, :, cur_lo: day_idx + 1].sum(-1).astype(float)
    hist = cnt[:, :, base_lo:cur_lo].reshape(cnt.shape[0], cnt.shape[1], B, 7).sum(-1).astype(float)
    H = hist.sum(-1)
    # exposure: store volume in other categories, current (per week) vs baseline weekly mean
    other_cur = (cur.sum(1, keepdims=True) - cur) / scale
    other_hist = (H.sum(1, keepdims=True) - H) / B
    exposure_ratio = np.clip((other_cur + 1) / (other_hist + 1), *settings.exposure_ratio_bounds)
    # network trend: same category in all other stores (leave-one-out)
    loo_cur = (cur.sum(0, keepdims=True) - cur) / scale
    loo_hist = (H.sum(0, keepdims=True) - H) / B
    network_ratio = np.clip((loo_cur + 1) / (loo_hist + 1), *settings.network_ratio_bounds)
    # empirical-Bayes weekly baseline (prior = category share x store weekly volume)
    share = H.sum(0) / max(H.sum(), 1)
    lam_prior = share[None, :] * (H.sum(1) / B)[:, None]
    m = settings.prior_strength_weeks
    lam_base = np.maximum((H + m * lam_prior) / (B + m), 0.05)
    expected = lam_base * scale * exposure_ratio * network_ratio
    # category over-dispersion of weekly counts, pooled over stores
    means, var = hist.mean(-1), hist.var(-1, ddof=1)
    disp = np.ones(cnt.shape[1])
    for c in range(cnt.shape[1]):
        mask = means[:, c] > 0
        if means[mask, c].sum() > 0:
            disp[c] = var[mask, c].sum() / means[mask, c].sum()
    dispersion = np.broadcast_to(np.clip(disp, *settings.dispersion_bounds)[None, :], cur.shape)
    return {"cur": cur, "H": H, "B": B, "lam_base": lam_base, "exposure_ratio": exposure_ratio,
            "network_ratio": network_ratio, "expected": expected, "dispersion": dispersion,
            "p": _tail_probability(cur, expected, dispersion)}


def detect_at(cube: CountCube, day_idx: int,
              settings: config.DetectionSettings = config.DETECTION) -> pd.DataFrame | None:
    """Score every (store, category) cell for windows ending on ``day_idx``.

    Each scan window (e.g. 7 and 14 days) is tested separately; the smallest
    p-value is Bonferroni-corrected for the number of windows, then
    Benjamini-Hochberg is applied across all cells. Returns None when there is
    not enough history for a baseline.
    """
    windows = [w for w in settings.scan_windows_days]
    results = [_window_stats(cube, day_idx, w, settings) for w in windows]
    if any(r is None for r in results):
        return None
    P = np.stack([r["p"] for r in results])  # windows x S x C
    best = P.argmin(0)
    p = np.minimum(P.min(0) * len(windows), 1.0)

    def pick(key):
        return np.take_along_axis(np.stack([r[key] for r in results]), best[None], 0)[0]

    cur_w, expected, lam_base = pick("cur"), pick("expected"), pick("lam_base")
    exposure_ratio, network_ratio, dispersion = pick("exposure_ratio"), pick("network_ratio"), pick("dispersion")
    window_days = np.array(windows)[best]
    rep = results[windows.index(settings.current_window_days)] if settings.current_window_days in windows else results[0]
    cur7 = rep["cur"]
    W = settings.current_window_days
    cur_reports = cube.reports[:, :, day_idx - W + 1: day_idx + 1].sum(-1)

    testable = np.array([c != NO_ISSUE for c in cube.categories])[None, :].repeat(cur7.shape[0], 0)
    q = np.ones_like(p)
    q[testable] = benjamini_hochberg(p[testable])
    sev = np.array([CATEGORY_BY_CODE[c].base_severity for c in cube.categories])
    fdr = np.array([settings.fdr_by_severity[s] for s in sev])[None, :]
    rate_ratio = cur_w / expected
    abs_increase = cur_w - expected
    flagged = (testable & (q <= fdr) & (cur_w >= settings.min_current_count)
               & (abs_increase >= settings.min_absolute_increase) & (rate_ratio >= settings.min_rate_ratio))
    watch = testable & ~flagged & (p <= settings.watch_p_value) & (cur_w >= settings.min_current_count)

    # persistence: how many of the last 4 weekly windows were elevated vs the weekly baseline
    weekly_base = rep["lam_base"]
    threshold = np.maximum(2, weekly_base + 2 * np.sqrt(weekly_base * rep["dispersion"]))
    persistence = np.zeros_like(cur7, dtype=int)
    for k in range(4):
        hi = day_idx + 1 - 7 * k
        if hi - 7 >= 0:
            persistence += (cube.counts[:, :, hi - 7:hi].sum(-1) >= threshold).astype(int)

    S, C = cur7.shape
    out = pd.DataFrame({
        "store_id": np.repeat(cube.store_ids, C),
        "category": np.tile(cube.categories, S),
        "current_count": cur7.ravel().astype(int),
        "current_reports": cur_reports.ravel().astype(int),
        "baseline_weekly_mean": (rep["H"] / rep["B"]).ravel().round(3),
        "baseline_weeks": rep["B"],
        "baseline_eb": weekly_base.ravel().round(3),
        "evidence_window_days": window_days.ravel(),
        "window_count": cur_w.ravel().astype(int),
        "exposure_ratio": exposure_ratio.ravel().round(3),
        "network_ratio": network_ratio.ravel().round(3),
        "expected_count": expected.ravel().round(3),
        "dispersion": dispersion.ravel().round(3),
        "p_value": p.ravel(),
        "q_value": q.ravel(),
        "z_score": ((cur_w - expected) / np.sqrt(expected * dispersion)).ravel().round(2),
        "rate_ratio": rate_ratio.ravel().round(2),
        "absolute_increase": abs_increase.ravel().round(2),
        "persistence_weeks": persistence.ravel().astype(int),
        "flagged": flagged.ravel(),
        "watch": watch.ravel(),
    })
    out["as_of"] = cube.days[day_idx] + pd.Timedelta(hours=23, minutes=59, seconds=59)
    out["signal"] = np.where(out["flagged"], "Emerging", np.where(out["watch"], "Watch", ""))
    return out


def score_cells(processed: pd.DataFrame, stores: pd.DataFrame, as_of=None,
                settings: config.DetectionSettings = config.DETECTION) -> pd.DataFrame | None:
    """Statistics for every (store, category) cell at ``as_of`` (data after as_of is ignored)."""
    as_of = pd.Timestamp(as_of or processed["timestamp"].max()).normalize()
    cube = build_cube(processed, stores["store_id"].tolist(), end=as_of)
    return detect_at(cube, cube.day_index(as_of), settings)


def detect_emerging(processed: pd.DataFrame, stores: pd.DataFrame, as_of=None,
                    settings: config.DetectionSettings = config.DETECTION,
                    include_watch: bool = True, cells: pd.DataFrame | None = None) -> pd.DataFrame:
    """User-facing detection at ``as_of`` with evidence and explanations."""
    as_of = pd.Timestamp(as_of or processed["timestamp"].max()).normalize()
    res = cells if cells is not None else score_cells(processed, stores, as_of, settings)
    if res is None:
        return pd.DataFrame()
    sel = res[res["flagged"] | (res["watch"] & include_watch)].copy()
    if sel.empty:
        return sel
    window_start = as_of - pd.Timedelta(days=settings.current_window_days - 1)
    window = processed[(processed["timestamp"] >= window_start) & (processed["timestamp"] < as_of + pd.Timedelta(days=1))]
    store_info = stores.set_index("store_id")
    rows = []
    for r in sel.itertuples(index=False):
        ev = window[(window["store_id"] == r.store_id) & (window["pred_category"] == r.category)]
        ev = ev.sort_values("timestamp")
        cat = CATEGORY_BY_CODE[r.category]
        owner, secondary = routing.assign_owner(r.category)
        severity = ev["policy_severity"].map({"Critical": 4, "High": 3, "Medium": 2, "Low": 1}).max() if len(ev) else 0
        severity = {4: "Critical", 3: "High", 2: "Medium", 1: "Low"}.get(severity, cat.base_severity)
        rows.append({
            **r._asdict(),
            "store_name": store_info.loc[r.store_id, "store_name"],
            "region": store_info.loc[r.store_id, "region"],
            "store_format": store_info.loc[r.store_id, "format"],
            "category_label": cat.label,
            "severity": severity,
            "owner": owner,
            "secondary_owner": secondary or "",
            "channels": ", ".join(sorted(ev["channel"].unique())),
            "n_channels": int(ev["channel"].nunique()),
            "evidence_ids": ev["feedback_id"].tolist(),
            "first_report": ev["timestamp"].min(),
            "last_report": ev["timestamp"].max(),
            "relative_change": (r.window_count - r.expected_count) / r.expected_count,
            "recommended_action": routing.recommended_action(r.category, "Emerging trend", severity, False),
            "explanation": explain_signal(r, cat.label),
        })
    out = pd.DataFrame(rows)
    out["detection_time"] = out["as_of"]
    return out.sort_values(["flagged", "p_value"], ascending=[False, True]).reset_index(drop=True)


def explain_signal(r, label: str) -> str:
    status = "flagged as EMERGING" if r.flagged else "placed on WATCH (not confirmed)"
    return (
        f"{label}: {r.current_count} estimated unique incidents ({r.current_reports} reports) in the last 7 days "
        f"vs a historical baseline of {r.baseline_weekly_mean:.2f}/week over {r.baseline_weeks} weeks "
        f"(empirical-Bayes {r.baseline_eb:.2f}/week). Strongest evidence over the last {r.evidence_window_days} "
        f"days: {r.window_count} incidents observed vs {r.expected_count:.2f} expected after adjusting for store "
        f"volume (x{r.exposure_ratio:.2f}) and the network trend for this category (x{r.network_ratio:.2f}). "
        f"Probability of this many or more by chance p={r.p_value:.2g} (window-corrected; BH q={r.q_value:.2g}, "
        f"z={r.z_score:.1f}); {status}."
    )


def rolling_detection(processed: pd.DataFrame, stores: pd.DataFrame, start=None, end=None,
                      settings: config.DetectionSettings = config.DETECTION) -> pd.DataFrame:
    """Run the detector for every as-of day in [start, end] using only data up to each day.

    Returns all flagged/watch cells with their as-of day (used for lead-time and
    false-positive evaluation).
    """
    cube = build_cube(processed, stores["store_id"].tolist())
    first = cube.day_index(start) if start is not None else 0
    last = cube.day_index(end) if end is not None else len(cube.days) - 1
    frames = []
    for d in range(first, last + 1):
        res = detect_at(cube, d, settings)
        if res is not None:
            frames.append(res[res["flagged"] | res["watch"]])
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def network_movements(processed: pd.DataFrame, as_of=None, weeks: int = 4) -> pd.DataFrame:
    """Category-level network view: unique incidents per week for the last ``weeks`` weeks."""
    as_of = pd.Timestamp(as_of or processed["timestamp"].max()).normalize()
    lo = as_of - pd.Timedelta(days=7 * weeks - 1)
    sub = processed[(processed["timestamp"] >= lo) & processed["is_cluster_anchor"]
                    & processed["pred_category"].isin(OPERATIONAL_CODES)].copy()
    sub["week_ending"] = as_of - pd.to_timedelta(((as_of - sub["timestamp"].dt.normalize()).dt.days // 7) * 7, unit="D")
    piv = sub.pivot_table(index="pred_category", columns="week_ending", values="feedback_id", aggfunc="count",
                          fill_value=0)
    piv.index = [category_label(c) for c in piv.index]
    return piv
