"""Case building and explainable operational prioritisation.

A *case* is the unit that operations teams manage. Cases come from two sources:

* **Policy escalations** - reports in the case window that trigger a policy rule.
  Each Critical cluster becomes its own case; High-severity policy reports are
  grouped per store x category x week.
* **Emerging trends** - confirmed signals from the anomaly detector. If policy
  reports exist for the same store x category they are attached to the trend
  case.

Ranking
-------
Policy-mandated escalation overrides ordinary ranking through *tiers*:

* P1 - Critical policy escalation (24h), regardless of report volume;
* P2 - High-severity policy review, or an emerging trend of High/Critical severity;
* P3 - other emerging trends.

Within a tier, cases are ranked by a 0-100 priority score built from features
normalised to [0, 1]: severity, evidence strength, trend, breadth (other
stores in the region showing the same signal) and persistence.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

import config
from src import routing
from src.taxonomy import (CATEGORY_BY_CODE, POLICY_RULE_BY_ID, SEVERITY_LEVELS, SEVERITY_RANK, TREND_ESCALATION,
                          UNCLASSIFIED, category_label)

TIER_LABELS = {
    1: "P1 - Mandatory escalation",
    2: "P2 - Mandatory review / high-severity trend",
    3: "P3 - Emerging trend",
}


def _iso_week(ts: pd.Timestamp) -> str:
    y, w, _ = ts.isocalendar()
    return f"{y}W{w:02d}"


def _policy_category(row) -> str:
    """Category used to group a policy report (falls back to the rule's category)."""
    if row["pred_category"] != UNCLASSIFIED:
        return row["pred_category"]
    rule = POLICY_RULE_BY_ID.get(str(row["policy_rules"]).split(",")[0])
    return rule.categories[0] if rule else UNCLASSIFIED


def _max_sev(values) -> str:
    vals = [v for v in values if v in SEVERITY_RANK]
    return max(vals, key=lambda s: SEVERITY_RANK[s]) if vals else "Low"


def _evidence_from_reports(ev: pd.DataFrame) -> float:
    conf = float(ev["confidence"].mean()) if len(ev) else 0.0
    n_rep = len(ev)
    n_ch = ev["channel"].nunique() if len(ev) else 0
    return 0.5 * conf + 0.25 * min(1.0, (n_rep - 1) / 3) + 0.25 * min(1.0, (n_ch - 1) / 2)


def build_cases(processed: pd.DataFrame, stores: pd.DataFrame, signals: pd.DataFrame,
                cells: pd.DataFrame | None, as_of=None,
                settings: config.PrioritySettings = config.PRIORITY) -> pd.DataFrame:
    as_of = pd.Timestamp(as_of or processed["timestamp"].max()).normalize()
    lo = as_of - pd.Timedelta(days=settings.case_window_days - 1)
    hi = as_of + pd.Timedelta(days=1)
    window = processed[(processed["timestamp"] >= lo) & (processed["timestamp"] < hi)]
    week = _iso_week(as_of)
    store_info = stores.set_index("store_id")

    breadth = {}
    if cells is not None and len(cells):
        elevated = cells[(cells["z_score"] >= 2) & (cells["current_count"] >= 2)].merge(
            stores[["store_id", "region"]], on="store_id")
        breadth = elevated.groupby(["region", "category"])["store_id"].nunique().to_dict()

    cases: dict[str, dict] = {}

    # ---- emerging trends
    confirmed = signals[signals["flagged"]] if len(signals) else signals
    trend_keys = set()
    for s in confirmed.itertuples(index=False):
        trend_keys.add((s.store_id, s.category))
        ev = window[window["feedback_id"].isin(s.evidence_ids)]
        stat_evidence = min(1.0, -math.log10(max(s.q_value, 1e-12)) / 8)
        trend = 0.6 * min(1.0, math.log2(max(s.rate_ratio, 1)) / 4) + 0.4 * min(1.0, s.absolute_increase / 10)
        cases[f"TRD-{s.store_id}-{s.category}-{week}"] = {
            "case_type": "Emerging trend",
            "store_id": s.store_id, "category": s.category,
            "evidence": ev,
            "components": {
                "evidence": max(stat_evidence, _evidence_from_reports(ev)),
                "trend": trend,
                "persistence": s.persistence_weeks / 4,
            },
            "signal": s._asdict(),
        }

    # ---- policy escalations
    pol = window[window["mandatory_escalation"]].copy()
    if len(pol):
        pol["case_category"] = pol.apply(_policy_category, axis=1)
        for cluster_id, grp in pol[pol["policy_severity"] == "Critical"].groupby("cluster_id"):
            key = (grp["store_id"].iloc[0], grp["case_category"].iloc[0])
            members = processed[processed["cluster_id"] == cluster_id]
            if key in trend_keys:
                _attach(cases, key, week, members)
                continue
            cases[f"POL-{cluster_id}"] = _policy_case(key, members)
        high = pol[pol["policy_severity"] != "Critical"]
        for (store_id, cat), grp in high.groupby(["store_id", "case_category"]):
            key = (store_id, cat)
            if key in trend_keys:
                _attach(cases, key, week, grp)
                continue
            cases[f"POL-{store_id}-{cat}-{week}"] = _policy_case(key, grp)

    rows = []
    for case_id, c in cases.items():
        ev = c["evidence"].sort_values("timestamp")
        store_id, cat = c["store_id"], c["category"]
        severity = _max_sev(list(ev["policy_severity"]) + [CATEGORY_BY_CODE[cat].base_severity
                                                           if cat in CATEGORY_BY_CODE else "Low"])
        mandatory = bool(ev["mandatory_escalation"].any()) if len(ev) else False
        sig = c.get("signal") or {}
        trend_escalated = False
        if sig and sig["q_value"] <= TREND_ESCALATION["max_q_value"] and \
                SEVERITY_RANK[severity] < SEVERITY_RANK[TREND_ESCALATION["cap"]]:
            severity = SEVERITY_LEVELS[SEVERITY_LEVELS.index(severity) - 1]
            trend_escalated = True
        rules = sorted({r for v in ev["policy_rules"] for r in str(v).split(",") if r})
        region = store_info.loc[store_id, "region"]
        comp = {
            "severity": settings.severity_scores[severity],
            "evidence": c["components"]["evidence"],
            "trend": c["components"]["trend"],
            "breadth": min(1.0, max(0, breadth.get((region, cat), 1) - 1) / 4),
            "persistence": c["components"]["persistence"],
        }
        comp = {k: round(float(np.clip(v, 0, 1)), 3) for k, v in comp.items()}
        score = round(100 * sum(settings.weights[k] * v for k, v in comp.items()), 1)
        is_trend = c["case_type"].startswith("Emerging")
        if mandatory and severity == "Critical":
            tier = 1
        elif mandatory or (is_trend and SEVERITY_RANK[severity] >= SEVERITY_RANK["High"]):
            tier = 2
        else:
            tier = 3
        escalation = ("Mandatory escalation (24h)" if tier == 1 else
                      "Mandatory review (72h)" if mandatory else "Trend escalation (72h)")
        owner, secondary = routing.assign_owner(cat)
        explanation = _explain(tier, severity, rules, comp, score, settings, sig, len(ev), trend_escalated)
        rows.append({
            "case_id": case_id,
            "case_type": c["case_type"],
            "tier": tier,
            "tier_label": TIER_LABELS[tier],
            "priority_score": score,
            "priority_components": json.dumps(comp),
            "store_id": store_id,
            "store_name": store_info.loc[store_id, "store_name"],
            "region": region,
            "category": cat,
            "category_label": category_label(cat),
            "severity": severity,
            "escalation": escalation,
            "mandatory_escalation": mandatory,
            "trend_escalated": trend_escalated,
            "policy_rules": ",".join(rules),
            "owner": owner,
            "secondary_owner": secondary or "",
            "recommended_action": routing.recommended_action(cat, "Emerging trend" if is_trend else "Policy",
                                                             severity, mandatory),
            "n_reports": int(len(ev)),
            "n_unique_incidents": int(ev["cluster_id"].nunique()) if len(ev) else 0,
            "channels": ", ".join(sorted(ev["channel"].unique())) if len(ev) else "",
            "first_report": ev["timestamp"].min() if len(ev) else pd.NaT,
            "last_report": ev["timestamp"].max() if len(ev) else pd.NaT,
            "evidence_ids": json.dumps(ev["feedback_id"].tolist()),
            "baseline_weekly_mean": sig.get("baseline_weekly_mean", np.nan),
            "current_count": sig.get("current_count", np.nan),
            "expected_count": sig.get("expected_count", np.nan),
            "p_value": sig.get("p_value", np.nan),
            "q_value": sig.get("q_value", np.nan),
            "rate_ratio": sig.get("rate_ratio", np.nan),
            "detection_time": sig.get("as_of", as_of + pd.Timedelta(hours=23, minutes=59, seconds=59)),
            "explanation": explanation,
            "default_verification": "Allegation (unverified)",
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["tier", "priority_score"], ascending=[True, False]).reset_index(drop=True)


def _policy_case(key, evidence: pd.DataFrame) -> dict:
    return {
        "case_type": "Policy escalation",
        "store_id": key[0], "category": key[1],
        "evidence": evidence,
        "components": {"evidence": _evidence_from_reports(evidence), "trend": 0.0, "persistence": 0.0},
    }


def _attach(cases: dict, key, week: str, evidence: pd.DataFrame) -> None:
    case = cases[f"TRD-{key[0]}-{key[1]}-{week}"]
    case["evidence"] = pd.concat([case["evidence"], evidence]).drop_duplicates("feedback_id")
    case["case_type"] = "Emerging trend + policy"


def _explain(tier, severity, rules, comp, score, settings, sig, n_reports, trend_escalated=False) -> str:
    parts = []
    if tier == 1:
        parts.append(f"Tier P1: policy {', '.join(rules)} mandates escalation of {severity} allegations "
                     f"regardless of volume ({n_reports} report(s)). This ranks above ordinary scoring.")
    elif tier == 2 and rules:
        parts.append(f"Tier P2: policy {', '.join(rules)} requires review of {severity} reports.")
    elif tier == 2:
        parts.append(f"Tier P2: emerging trend with {severity} severity.")
    if trend_escalated:
        parts.append(f"Severity raised one level to {severity} by the trend-escalation rule (confirmed "
                     f"emerging trend, q <= {TREND_ESCALATION['max_q_value']}).")
    else:
        parts.append("Tier P3: emerging trend.")
    if sig:
        parts.append(f"Trend evidence: {sig.get('window_count')} incidents vs {sig.get('expected_count'):.2f} "
                     f"expected over {sig.get('evidence_window_days')} days (q={sig.get('q_value'):.2g}).")
    formula = " + ".join(f"{k} {comp[k]:.2f}x{settings.weights[k]:.2f}" for k in settings.weights)
    parts.append(f"Score {score:.0f}/100 = 100 x ({formula}).")
    parts.append("Not verified: every case starts as an allegation until investigated.")
    return " ".join(parts)
