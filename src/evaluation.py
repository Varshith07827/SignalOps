"""Reproducible evaluation against SYNTHETIC ground truth.

Run ``python -m src.evaluation`` (writes ``artifacts/evaluation_report.json``
and exits non-zero if any planted-scenario check fails).

Every figure produced here is a synthetic-data evaluation of our own generator
and planted scenarios. It is NOT an official hackathon result and does not
say how the system would perform on real retailer feedback.

Leakage controls
----------------
* The classifier is trained on a separate corpus (different seed) that only
  uses "train" phrasing templates; ~25% of templates are hold-out only.
* Classification metrics are reported at the *incident* level (one record per
  true incident) so duplicate reports of the same incident are not counted as
  independent evidence, and separately for hold-out phrasings.
* Emerging-issue lead time uses a rolling replay in which each as-of day only
  sees data up to that day.
"""
from __future__ import annotations

import argparse
import sys
import itertools
import json
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

import config
from src import anomaly_detection, data_generator, storage
from src.taxonomy import (CATEGORY_BY_CODE, CATEGORY_CODES, OUT_OF_TAXONOMY, POLICY_RULES, SEVERITY_LEVELS,
                          UNCLASSIFIED)

LIMITATIONS = [
    "All metrics are computed on synthetic data produced by our own generator; templates, vocabulary "
    "and noise were designed by the same team that built the classifier, so results are optimistic.",
    "Hold-out templates measure generalisation to unseen phrasings only within the synthetic vocabulary, "
    "not to genuinely new language, slang or scripts.",
    "Only a small controlled set of Hinglish and transliterated regional phrases is supported; other "
    "languages should be routed to human review.",
    "Planted incidents were designed by us and are not the organisers' hidden incidents. Detection rate on "
    "two planted trends is not a statistically meaningful sensitivity estimate.",
    "Ground-truth duplicate groups are defined by the generator; real duplicate structure will differ.",
    "Taxonomy, ownership mappings and severity policy are provisional assumptions.",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def load_joined() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Processed records joined with ground truth (evaluation only)."""
    processed = storage.read_table("feedback")
    raw, stores, manifest = data_generator.load_raw()
    gt = raw[["feedback_id"] + config.GROUND_TRUTH_COLUMNS]
    joined = processed.merge(gt, on="feedback_id", how="inner", validate="one_to_one")
    return joined, stores, manifest


def _prf(y_true, y_pred, labels) -> dict:
    p, r, f, _ = precision_recall_fscore_support(y_true, y_pred, labels=labels, average="macro", zero_division=0)
    pw, rw, fw, _ = precision_recall_fscore_support(y_true, y_pred, labels=labels, average="weighted",
                                                    zero_division=0)
    return {"macro_precision": round(p, 4), "macro_recall": round(r, 4), "macro_f1": round(f, 4),
            "weighted_precision": round(pw, 4), "weighted_recall": round(rw, 4), "weighted_f1": round(fw, 4),
            "n": int(len(y_true))}


def _pairs(groups) -> set:
    out = set()
    for g in groups:
        if len(g) > 1:
            out.update(itertools.combinations(sorted(g), 2))
    return out


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def evaluate_classification(df: pd.DataFrame) -> dict:
    labels = CATEGORY_CODES
    in_tax = df[df["true_issue_category"] != OUT_OF_TAXONOMY]
    incident_level = in_tax.sort_values("timestamp").drop_duplicates("incident_id")

    def block(x: pd.DataFrame) -> dict:
        covered = x[x["decision"] != "unknown"]
        res = _prf(x["true_issue_category"], x["pred_category"], labels)
        res["coverage"] = round(float(len(covered) / max(len(x), 1)), 4)
        res["accuracy_all"] = round(float((x["pred_category"] == x["true_issue_category"]).mean()), 4)
        res["accuracy_when_classified"] = round(float((covered["pred_category"] ==
                                                       covered["true_issue_category"]).mean()), 4)
        return res

    per_class = precision_recall_fscore_support(incident_level["true_issue_category"],
                                                incident_level["pred_category"], labels=labels, zero_division=0)
    per_class_rows = [{"category": c, "label": CATEGORY_BY_CODE[c].label, "precision": round(float(per_class[0][i]), 3),
                       "recall": round(float(per_class[1][i]), 3), "f1": round(float(per_class[2][i]), 3),
                       "support": int(per_class[3][i])} for i, c in enumerate(labels)]
    cm_labels = labels + [UNCLASSIFIED]
    cm = confusion_matrix(incident_level["true_issue_category"], incident_level["pred_category"], labels=cm_labels)
    other = df[df["true_issue_category"] == OUT_OF_TAXONOMY]
    by_lang = (incident_level.assign(correct=incident_level["pred_category"] == incident_level["true_issue_category"])
               .groupby("true_language")["correct"].agg(["mean", "count"]).round(4))
    return {
        "incident_level_all": block(incident_level),
        "incident_level_holdout_templates": block(incident_level[incident_level["template_split"] == "holdout"]),
        "incident_level_train_templates": block(incident_level[incident_level["template_split"] == "train"]),
        "record_level_all": block(in_tax),
        "per_class_incident_level": per_class_rows,
        "confusion_matrix": {"labels": cm_labels[:-1] + [UNCLASSIFIED], "rows_true": labels,
                             "matrix": cm[: len(labels)].tolist()},
        "out_of_taxonomy": {
            "n": int(len(other)),
            "abstained_unclassified": round(float((other["decision"] == "unknown").mean()), 4) if len(other) else None,
            "flagged_for_review": round(float((other["decision"] == "review").mean()), 4) if len(other) else None,
            "forced_auto_label": round(float((other["decision"] == "auto").mean()), 4) if len(other) else None,
        },
        "accuracy_by_language": {lang: {"accuracy": float(r["mean"]), "n": int(r["count"])}
                                 for lang, r in by_lang.iterrows()},
    }


# --------------------------------------------------------------------------- #
# Severity and escalation
# --------------------------------------------------------------------------- #
def escalation_precision(escalated_true_actionable: int, escalated_total: int) -> float | None:
    """True actionable escalations / all escalations."""
    if escalated_total == 0:
        return None
    return escalated_true_actionable / escalated_total


def evaluate_escalation(df: pd.DataFrame, cases: pd.DataFrame, manifest: dict) -> dict:
    high_true = df["true_actionable"] & df["true_severity"].isin(["Critical", "High"])
    esc = df[df["mandatory_escalation"]]
    tp = int((esc["true_actionable"] & esc["true_severity"].isin(["Critical", "High"])).sum())
    policy_cats = {c for r in POLICY_RULES for c in r.categories}
    true_policy = df[df["true_issue_category"].isin(policy_cats)]
    crit = df[df["true_severity"] == "Critical"]

    # case level
    gt = df.set_index("feedback_id")
    planted_keys = {(s["store_id"], s["category"]) for k, s in manifest["scenarios"].items() if k in ("A", "C")}
    case_rows = []
    for c in cases.itertuples():
        ids = json.loads(c.evidence_ids)
        ev = gt.loc[[i for i in ids if i in gt.index]]
        if c.case_type.startswith("Emerging"):
            ok = (c.store_id, c.category) in planted_keys
            reason = "matches planted trend" if ok else "no planted trend for this store/category"
        else:
            share = float((ev["true_actionable"] & ev["true_severity"].isin(["Critical", "High"])).mean()) if len(ev) else 0
            ok = share >= 0.5
            reason = f"{share:.0%} of evidence is truly actionable High/Critical"
        case_rows.append({"case_id": c.case_id, "case_type": c.case_type, "tier": int(c.tier), "true_positive": bool(ok),
                          "reason": reason})
    case_eval = pd.DataFrame(case_rows)
    sev_cm = confusion_matrix(df["true_severity"], df["policy_severity"], labels=SEVERITY_LEVELS)
    return {
        "record_level": {
            "escalations": int(len(esc)),
            "true_actionable_escalations": tp,
            "escalation_precision": round(escalation_precision(tp, len(esc)) or 0, 4),
            "recall_of_true_high_critical": round(float(df.loc[high_true, "mandatory_escalation"].mean()), 4),
            "recall_of_true_critical": round(float(crit["mandatory_escalation"].mean()), 4) if len(crit) else None,
            "recall_of_policy_category_reports": round(float(true_policy["mandatory_escalation"].mean()), 4),
            "definition": "Escalation = record with a mandatory policy escalation. True actionable = ground truth "
                          "says actionable AND true severity is High or Critical.",
        },
        "case_level": {
            "escalated_cases": int(len(case_eval)),
            "true_actionable_cases": int(case_eval["true_positive"].sum()) if len(case_eval) else 0,
            "escalation_precision": round(float(case_eval["true_positive"].mean()), 4) if len(case_eval) else None,
            "false_positive_cases": case_eval[~case_eval["true_positive"]].to_dict("records") if len(case_eval) else [],
            "definition": "Policy case is a true positive when at least half of its evidence records are truly "
                          "actionable High/Critical; a trend case when it matches a planted trend scenario.",
        },
        "severity_confusion": {"labels": SEVERITY_LEVELS, "matrix": sev_cm.tolist()},
    }


# --------------------------------------------------------------------------- #
# Deduplication
# --------------------------------------------------------------------------- #
def evaluate_dedup(df: pd.DataFrame) -> dict:
    pred = _pairs(df.groupby("cluster_id")["feedback_id"].apply(list))
    true = _pairs(df.groupby("incident_id")["feedback_id"].apply(list))
    tp = len(pred & true)
    precision = tp / len(pred) if pred else None
    recall = tp / len(true) if true else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    return {
        "pairwise_precision": round(precision, 4) if precision is not None else None,
        "pairwise_recall": round(recall, 4) if recall is not None else None,
        "pairwise_f1": round(f1, 4) if f1 is not None else None,
        "predicted_duplicate_pairs": len(pred),
        "true_duplicate_pairs": len(true),
        "total_records": int(len(df)),
        "estimated_unique_incidents": int(df["cluster_id"].nunique()),
        "true_unique_incidents": int(df["incident_id"].nunique()),
        "possible_duplicates_flagged": int((df["dup_status"] == "possible duplicate").sum()),
        "possible_duplicates_truly_duplicate": round(float(_possible_dup_accuracy(df)), 4),
    }


def _possible_dup_accuracy(df: pd.DataFrame) -> float:
    pos = df[df["dup_status"] == "possible duplicate"]
    if pos.empty:
        return float("nan")
    anchors = df[df["is_cluster_anchor"]].set_index("cluster_id")["incident_id"]
    target = pos["possible_duplicate_of"].map(anchors)
    return float((target == pos["incident_id"]).mean())


# --------------------------------------------------------------------------- #
# Emerging-issue detection
# --------------------------------------------------------------------------- #
def _episodes(flags: pd.DataFrame, gap_days: int = 7) -> pd.DataFrame:
    rows = []
    for (s, c), g in flags.groupby(["store_id", "category"]):
        days = sorted(pd.to_datetime(g["as_of"]).dt.normalize().unique())
        start = prev = days[0]
        for d in days[1:]:
            if (d - prev).days > gap_days:
                rows.append((s, c, start, prev))
                start = d
            prev = d
        rows.append((s, c, start, prev))
    return pd.DataFrame(rows, columns=["store_id", "category", "first_flag", "last_flag"])


def naive_volume_ranking(df: pd.DataFrame, stores: pd.DataFrame, first_day, top_n: int = 10) -> pd.DataFrame:
    """Baseline the brief warns against: flag the top-N cells by raw 7-day report volume each day."""
    cube = anomaly_detection.build_cube(df, stores["store_id"].tolist())
    cum = cube.reports.cumsum(-1)
    rows = []
    for d in range(max(cube.day_index(first_day), 7), len(cube.days)):
        window = cum[:, :, d] - cum[:, :, d - 7]
        flat = window.ravel()
        top = np.argsort(flat)[::-1][:top_n]
        for idx in top:
            if flat[idx] > 0:
                s, c = np.unravel_index(idx, window.shape)
                rows.append({"store_id": cube.store_ids[s], "category": cube.categories[c],
                             "as_of": cube.days[d] + pd.Timedelta(hours=23, minutes=59, seconds=59)})
    return pd.DataFrame(rows)


def evaluate_detection(df: pd.DataFrame, stores: pd.DataFrame, manifest: dict) -> dict:
    roll = anomaly_detection.rolling_detection(df, stores)
    flags = roll[roll["flagged"]] if len(roll) else roll
    watches = roll[roll["flagged"] | roll["watch"]] if len(roll) else roll
    evaluable_from = str(pd.to_datetime(roll["as_of"]).min().date()) if len(roll) else None
    naive = naive_volume_ranking(df, stores, evaluable_from) if evaluable_from else pd.DataFrame()
    scenario_rows = {}
    planted_keys = {}
    for key in ("A", "C"):
        sc = manifest["scenarios"][key]
        planted_keys[(sc["store_id"], sc["category"])] = key
        onset = pd.Timestamp(sc["onset"])
        f = flags[(flags["store_id"] == sc["store_id"]) & (flags["category"] == sc["category"])
                  & (pd.to_datetime(flags["as_of"]) >= onset.normalize())] if len(flags) else flags
        detected = len(f) > 0
        det_time = pd.to_datetime(f["as_of"]).min() if detected else None
        planted = df[df["planted_scenario"] == key]
        w = watches[(watches["store_id"] == sc["store_id"]) & (watches["category"] == sc["category"])
                    & (pd.to_datetime(watches["as_of"]) >= onset.normalize())] if len(watches) else watches
        first_watch = pd.to_datetime(w["as_of"]).min() if len(w) else None
        nv = naive[(naive["store_id"] == sc["store_id"]) & (naive["category"] == sc["category"])
                   & (naive["as_of"] >= onset.normalize())] if len(naive) else naive
        naive_first = nv["as_of"].min() if len(nv) else None
        scenario_rows[key] = {
            "name": sc["name"], "store_id": sc["store_id"], "category": sc["category"],
            "onset": str(onset), "detected": bool(detected),
            "detection_time": str(det_time) if detected else None,
            "detection_delay_days": round((det_time - onset).total_seconds() / 86400, 2) if detected else None,
            "reports_before_detection": int((planted["timestamp"] <= det_time).sum()) if detected else None,
            "total_reports": int(len(planted)),
            "first_watch_time": str(first_watch) if first_watch is not None else None,
            "first_watch_delay_days": round((first_watch - onset).total_seconds() / 86400, 2)
            if first_watch is not None else None,
            "naive_top10_volume_first_time": str(naive_first) if naive_first is not None else None,
            "naive_first_delay_days": round((naive_first - onset).total_seconds() / 86400, 2)
            if naive_first is not None else None,
            "ongoing_at_end_of_data": bool(pd.Timestamp(sc["last_report"]).normalize()
                                           == df["timestamp"].max().normalize()),
        }
    # false positives: unplanted flag episodes, characterised with ground truth
    eps = _episodes(flags) if len(flags) else pd.DataFrame(columns=["store_id", "category", "first_flag", "last_flag"])
    eps["planted"] = [planted_keys.get((s, c)) for s, c in zip(eps["store_id"], eps["category"])]
    fps = eps[eps["planted"].isna()].copy()
    fp_rows = []
    for r in fps.itertuples():
        day = pd.Timestamp(r.first_flag)
        sub = df[(df["store_id"] == r.store_id) & (df["true_issue_category"] == r.category)]
        recent = sub[(sub["timestamp"] > day - pd.Timedelta(days=14)) & (sub["timestamp"] <= day + pd.Timedelta(days=1))]
        hist = sub[(sub["timestamp"] > day - pd.Timedelta(days=14 + 84)) & (sub["timestamp"] <= day - pd.Timedelta(days=14))]
        true_recent = recent["incident_id"].nunique()
        true_base = hist["incident_id"].nunique() / 12 * 2
        genuine = true_recent >= 3 and true_recent >= 2 * max(true_base, 0.5)
        fp_rows.append({"store_id": r.store_id, "category": r.category, "first_flag": str(day.date()),
                        "last_flag": str(pd.Timestamp(r.last_flag).date()),
                        "true_incidents_14d": int(true_recent), "true_expected_14d": round(true_base, 2),
                        "diagnosis": "genuine synthetic fluctuation (true count elevated)" if genuine
                        else "pipeline artefact (classification/dedup inflated count)"})
    n1 = manifest["negative_controls"]["N1"]
    n1_flags = flags[(flags["store_id"] == n1["store_id"]) & (flags["category"] == n1["category"])] if len(flags) else flags
    ac_flags = flags[flags["category"] == "store_temperature_ac"] if len(flags) else flags
    n_days = pd.to_datetime(roll["as_of"]).nunique() if len(roll) else 0
    detected = sum(v["detected"] for v in scenario_rows.values())
    naive_planted = int(sum((s_, c_) in planted_keys for s_, c_ in zip(naive["store_id"], naive["category"]))) \
        if len(naive) else 0
    n1_naive = int(((naive["store_id"] == n1["store_id"]) & (naive["category"] == n1["category"])).sum()) \
        if len(naive) else 0
    storepulse_flag_days = int(len(flags))
    return {
        "evaluable_from": evaluable_from,
        "as_of_days_replayed": int(n_days),
        "cells_per_day": int(len(stores) * (len(CATEGORY_CODES) - 1)),
        "planted_trends": scenario_rows,
        "detection_rate": round(detected / len(scenario_rows), 4),
        "false_positive_episodes": len(fp_rows),
        "false_positive_artefacts": sum(r["diagnosis"].startswith("pipeline") for r in fp_rows),
        "false_positive_flag_days": int(sum((s, c) not in planted_keys
                                            for s, c in zip(flags["store_id"], flags["category"]))),
        "false_positive_details": fp_rows,
        "storepulse_flag_days": storepulse_flag_days,
        "storepulse_flag_day_precision": round((storepulse_flag_days - int(sum(
            (s_, c_) not in planted_keys for s_, c_ in zip(flags["store_id"], flags["category"])))) /
            max(storepulse_flag_days, 1), 4),
        "naive_top10_baseline": {
            "flag_days": int(len(naive)),
            "planted_flag_days": naive_planted,
            "flag_day_precision": round(naive_planted / max(len(naive), 1), 4),
            "N1_chronic_store_flag_days": n1_naive,
        },
        "negative_control_N1_flag_days": int(len(n1_flags)),
        "negative_control_N2_ac_stores_flagged": int(ac_flags["store_id"].nunique()) if len(ac_flags) else 0,
        "definitions": {
            "onset": manifest["onset_definition"],
            "detection_delay": "detection time - onset (days). Both planted trends are still ongoing at the end "
                               "of the synthetic period.",
            "first_watch": "first as-of day the cell reached the non-escalated Watch level (raw p <= "
                           "watch threshold); an early warning, not a confirmed flag.",
            "naive_top10_baseline": "comparison method the brief warns against: each day flag the 10 store/"
                                    "category cells with the most raw reports in the last 7 days. Reported with its "
                                    "flag-day precision because it surfaces large, stable cells every day.",
            "false_positive_episode": "confirmed flags for a store/category with no planted trend; consecutive "
                                      "flag days within 7 days are one episode. Each is diagnosed against ground "
                                      "truth: 'genuine' if the true incident count in the preceding 14 days was "
                                      ">= 3 and at least twice its true baseline.",
        },
    }


# --------------------------------------------------------------------------- #
# Scenario checks
# --------------------------------------------------------------------------- #
def check_scenarios(df: pd.DataFrame, cases: pd.DataFrame, signals: pd.DataFrame, manifest: dict,
                    detection: dict | None = None) -> list[dict]:
    checks = []

    def add(scenario, name, ok, detail):
        checks.append({"scenario": scenario, "check": name, "passed": bool(ok), "detail": detail})

    for key in ("A", "C"):
        sc = manifest["scenarios"][key]
        sig = signals[(signals["store_id"] == sc["store_id"]) & (signals["category"] == sc["category"])
                      & (signals["flagged"])] if len(signals) else signals
        add(key, "flagged as emerging at as-of date", len(sig) == 1,
            f"{len(sig)} confirmed signal(s) for {sc['store_id']} / {sc['category']}")
        case = cases[(cases["store_id"] == sc["store_id"]) & (cases["category"] == sc["category"])
                     & cases["case_type"].str.startswith("Emerging")]
        owner = case["owner"].iloc[0] if len(case) else None
        add(key, f"routed to {sc['expected_owner']}", owner == sc["expected_owner"], f"owner={owner}")
        if detection:
            d = detection["planted_trends"][key]
            add(key, "detected in rolling replay (no look-ahead)", d["detected"],
                f"delay {d['detection_delay_days']} days after onset")
        if len(sig):
            add(key, "reports arrive through multiple channels", sig["n_channels"].iloc[0] >= 3,
                f"channels: {sig['channels'].iloc[0]}")
    sc = manifest["scenarios"]["B"]
    fid = sc["feedback_ids"][0]
    rec = df[df["feedback_id"] == fid].iloc[0]
    add("B", "single report", sc["n_reports"] == 1, f"{sc['n_reports']} report")
    add("B", "policy severity Critical", rec["policy_severity"] == "Critical", f"severity={rec['policy_severity']}")
    add("B", "mandatory escalation via POL-ALLERGEN", bool(rec["mandatory_escalation"]) and
        "POL-ALLERGEN" in rec["policy_rules"], f"rules={rec['policy_rules']}")
    add("B", "not claimed as verified", rec["verification_status"] == "Allegation (unverified)",
        rec["verification_status"])
    case = cases[cases["evidence_ids"].str.contains(fid, regex=False)]
    add("B", "P1 case created", len(case) == 1 and int(case["tier"].iloc[0]) == 1,
        f"case={case['case_id'].iloc[0] if len(case) else None}")
    expected = CATEGORY_BY_CODE[sc["category"]].owner
    add("B", f"routed per taxonomy ({expected})", len(case) == 1 and case["owner"].iloc[0] == expected,
        f"owner={case['owner'].iloc[0] if len(case) else None}")
    n1 = manifest["negative_controls"]["N1"]
    n1_sig = signals[(signals["store_id"] == n1["store_id"]) & (signals["category"] == n1["category"])
                     & signals["flagged"]] if len(signals) else signals
    add("N1", "chronic high-volume store not flagged as emerging", len(n1_sig) == 0,
        f"{n1['store_id']} stock_shortage flags at as-of: {len(n1_sig)}")
    return checks


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def run_evaluation(include_detection: bool = True, save: bool = True) -> dict:
    df, stores, manifest = load_joined()
    cases = storage.read_table("cases")
    signals = storage.read_table("signals") if storage.table_exists("signals") else pd.DataFrame()
    if len(signals) and "n_channels" not in signals.columns:
        signals["n_channels"] = signals["channels"].str.count(",") + 1
    detection = evaluate_detection(df, stores, manifest) if include_detection else None
    report = {
        "title": "StorePulse - SYNTHETIC-DATA evaluation",
        "disclaimer": config.SYNTHETIC_DISCLAIMER,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": manifest["generator"],
        "classification": evaluate_classification(df),
        "escalation": evaluate_escalation(df, cases, manifest),
        "deduplication": evaluate_dedup(df),
        "emerging_detection": detection,
        "scenario_checks": check_scenarios(df, cases, signals, manifest, detection),
        "limitations": LIMITATIONS,
    }
    if save:
        config.ensure_directories()
        config.EVALUATION_REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def print_report(r: dict) -> None:
    c = r["classification"]
    print("=" * 78)
    print(r["title"])
    print(r["disclaimer"])
    print("=" * 78)
    print("\nClassification (incident level; one record per true incident)")
    for name in ("incident_level_all", "incident_level_holdout_templates", "incident_level_train_templates"):
        b = c[name]
        print(f"  {name:<34} P={b['macro_precision']:.3f} R={b['macro_recall']:.3f} F1={b['macro_f1']:.3f} "
              f"coverage={b['coverage']:.3f} acc|classified={b['accuracy_when_classified']:.3f} n={b['n']}")
    o = c["out_of_taxonomy"]
    print(f"  out-of-taxonomy feedback (n={o['n']}): abstained {o['abstained_unclassified']:.1%}, "
          f"review {o['flagged_for_review']:.1%}, forced label {o['forced_auto_label']:.1%}")
    e = r["escalation"]
    print("\nEscalation")
    print(f"  record-level precision {e['record_level']['escalation_precision']:.3f} "
          f"({e['record_level']['true_actionable_escalations']}/{e['record_level']['escalations']}); "
          f"recall of true Critical {e['record_level']['recall_of_true_critical']:.3f}")
    if e["case_level"]["escalation_precision"] is not None:
        print(f"  case-level precision   {e['case_level']['escalation_precision']:.3f} "
              f"({e['case_level']['true_actionable_cases']}/{e['case_level']['escalated_cases']})")
    d = r["deduplication"]
    print("\nDeduplication")
    print(f"  pairwise P={d['pairwise_precision']} R={d['pairwise_recall']} F1={d['pairwise_f1']}; "
          f"estimated unique {d['estimated_unique_incidents']:,} vs true {d['true_unique_incidents']:,}")
    det = r["emerging_detection"]
    if det:
        print(f"\nEmerging-issue detection (rolling replay of {det['as_of_days_replayed']} as-of days)")
        for k, v in det["planted_trends"].items():
            print(f"  {k} {v['name']:<34} detected={v['detected']} confirmed after {v['detection_delay_days']}d "
                  f"(watch after {v['first_watch_delay_days']}d; naive top-10 after {v['naive_first_delay_days']}d) "
                  f"reports-before-detection={v['reports_before_detection']}/{v['total_reports']}")
        print(f"  detection rate {det['detection_rate']:.0%}; unplanted flag episodes {det['false_positive_episodes']} "
              f"of which pipeline artefacts {det['false_positive_artefacts']} "
              f"({det['false_positive_flag_days']} flag-days over {det['as_of_days_replayed']} days x "
              f"{det['cells_per_day']} cells)")
        for fp in det["false_positive_details"]:
            print(f"    - {fp['store_id']} {fp['category']} {fp['first_flag']}: {fp['diagnosis']} "
                  f"(true {fp['true_incidents_14d']} vs expected {fp['true_expected_14d']})")
        nb = det["naive_top10_baseline"]
        print(f"  flag-day precision: StorePulse {det['storepulse_flag_day_precision']:.1%} "
              f"({det['storepulse_flag_days']} flag-days) vs naive top-10 volume {nb['flag_day_precision']:.1%} "
              f"({nb['flag_days']} flag-days, N1 chronic store flagged on {nb['N1_chronic_store_flag_days']} days)")
        print(f"  N1 flag-days {det['negative_control_N1_flag_days']}; N2 AC stores flagged "
              f"{det['negative_control_N2_ac_stores_flagged']}")
    print("\nScenario checks")
    for ch in r["scenario_checks"]:
        print(f"  [{'PASS' if ch['passed'] else 'FAIL'}] {ch['scenario']}: {ch['check']} - {ch['detail']}")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # legacy Windows consoles: never crash on unusual characters
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Evaluate StorePulse against synthetic ground truth.")
    parser.add_argument("--skip-detection", action="store_true", help="Skip the rolling detection replay")
    args = parser.parse_args(argv)
    if not storage.table_exists("feedback"):
        from src.pipeline import run_pipeline
        run_pipeline()
    report = run_evaluation(include_detection=not args.skip_detection)
    print_report(report)
    print(f"\nSaved {config.EVALUATION_REPORT_PATH}")
    return 0 if all(c["passed"] for c in report["scenario_checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
