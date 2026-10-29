"""Model Evaluation: metrics against SYNTHETIC ground truth (never official results)."""
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src import ui
from src.taxonomy import category_label

ui.header("Model Evaluation", "How well does the pipeline recover the synthetic ground truth?")
st.markdown("<div class='sp-banner' style='border-left-color:#d03b3b'><b>SYNTHETIC-DATA EVALUATION.</b> Every "
            "figure on this page compares the pipeline with labels produced by our own synthetic generator. These are "
            "not official hackathon results and do not predict performance on real retailer feedback.</div>",
            unsafe_allow_html=True)
if not ui.data_ready():
    ui.empty_state("Run the pipeline first (Overview page).")
    st.stop()

meta = ui.load()["meta"]
report = json.loads(config.EVALUATION_REPORT_PATH.read_text(encoding="utf-8")) \
    if config.EVALUATION_REPORT_PATH.exists() else None
c1, c2 = st.columns([1, 3])
if c1.button("Run evaluation now", type="primary", width="stretch",
             help="Re-computes every metric, including a rolling replay of the detector (~10s)"):
    from src.evaluation import run_evaluation
    with st.spinner("Evaluating against synthetic ground truth ..."):
        report = run_evaluation()
    st.rerun()
if report is None:
    ui.empty_state("No evaluation report yet. Click 'Run evaluation now' or run `python -m src.evaluation`.")
    st.stop()
stale = report["generated_at"] < meta.get("processed_at", "")
c2.markdown(f"<div class='sp-sub' style='margin-top:8px'>Report generated {report['generated_at'].replace('T', ' ')} "
            f"on {report['dataset']['n_records']:,} records (seed {report['dataset']['seed']})"
            + (" · <b style='color:#fab219'>older than the latest pipeline run — re-run it</b>" if stale else "")
            + "</div>", unsafe_allow_html=True)

checks = pd.DataFrame(report["scenario_checks"])
passed = int(checks["passed"].sum())
cls, esc, dd, det = (report["classification"], report["escalation"], report["deduplication"],
                     report["emerging_detection"])
hold = cls["incident_level_holdout_templates"]
ui.metric_row([
    ("Scenario checks", f"{passed}/{len(checks)} pass", "planted incidents A, B, C + control N1"),
    ("Classification F1 (hold-out)", f"{hold['macro_f1']:.2f}",
     f"macro, unseen phrasings · all: {cls['incident_level_all']['macro_f1']:.2f}"),
    ("Escalation precision", f"{esc['record_level']['escalation_precision']:.1%}",
     f"case level {esc['case_level']['escalation_precision']:.1%}"),
    ("Dedup precision / recall", f"{dd['pairwise_precision']:.2f} / {dd['pairwise_recall']:.2f}", "pairwise, conservative"),
    ("Emerging detection rate", f"{det['detection_rate']:.0%}" if det else "—",
     f"{len(det['planted_trends'])} planted trends · {det['false_positive_episodes']} unplanted episodes" if det else ""),
])

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Scenario checks", "Classification", "Escalation & severity",
                                        "Deduplication", "Emerging-issue detection"])
with tab1:
    st.caption("Our own planted demonstration scenarios — not the organisers' hidden incidents.")
    checks["Result"] = np.where(checks["passed"], "✔ PASS", "✖ FAIL")
    st.dataframe(checks[["Result", "scenario", "check", "detail"]].rename(
        columns={"scenario": "Scenario", "check": "Check", "detail": "Detail"}), hide_index=True, width="stretch",
        height=38 + 35 * len(checks))

with tab2:
    st.caption("Metrics are computed at the incident level (one record per true incident) so duplicate reports are "
               "not counted as independent evidence. Hold-out templates are phrasings the classifier never saw "
               "during training; they are the most honest estimate here.")
    rows = []
    for key, name in (("incident_level_holdout_templates", "Hold-out phrasings (unseen)"),
                      ("incident_level_train_templates", "Training phrasings (seen)"),
                      ("incident_level_all", "All incidents"), ("record_level_all", "All records")):
        b = cls[key]
        rows.append({"Subset": name, "n": b["n"], "Macro precision": b["macro_precision"],
                     "Macro recall": b["macro_recall"], "Macro F1": b["macro_f1"], "Coverage": b["coverage"],
                     "Accuracy when classified": b["accuracy_when_classified"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    o = cls["out_of_taxonomy"]
    st.markdown(f"**Unknown handling** — out-of-taxonomy feedback (n={o['n']}): {o['abstained_unclassified']:.1%} left "
                f"unclassified, {o['flagged_for_review']:.1%} flagged for review, {o['forced_auto_label']:.1%} "
                "auto-labelled with a known category.")
    a, b = st.columns([1.3, 1])
    with a:
        cm = cls["confusion_matrix"]
        m = np.array(cm["matrix"], dtype=float)
        norm = m / np.maximum(m.sum(1, keepdims=True), 1)
        fig = go.Figure(go.Heatmap(
            z=norm.round(3), x=[category_label(c) for c in cm["labels"]], y=[category_label(c) for c in cm["rows_true"]],
            colorscale=ui.SEQUENTIAL, xgap=1, ygap=1, customdata=m.astype(int),
            colorbar=dict(title="row share", thickness=10),
            hovertemplate="true %{y}<br>predicted %{x}<br>%{customdata} incidents (%{z:.1%})<extra></extra>"))
        fig.update_layout(title=dict(text="Confusion matrix (incident level, row-normalised)", font=dict(size=13)))
        fig.update_xaxes(tickangle=-45, tickfont=dict(size=9), showgrid=False)
        fig.update_yaxes(autorange="reversed", tickfont=dict(size=9), showgrid=False)
        st.plotly_chart(ui.style_fig(fig, 620, legend=False), width="stretch")
    with b:
        pc = pd.DataFrame(cls["per_class_incident_level"]).sort_values("f1")
        st.markdown("**Per-category (incident level)**")
        st.dataframe(pc[["label", "precision", "recall", "f1", "support"]].rename(columns={"label": "Category"}),
                     hide_index=True, width="stretch", height=380)
        lang = pd.DataFrame([{"Language": k, "Accuracy": v["accuracy"], "n": v["n"]}
                             for k, v in cls["accuracy_by_language"].items()])
        st.markdown("**Accuracy by synthetic language tag**")
        st.dataframe(lang, hide_index=True, width="stretch")
        st.caption("'ml' (Malayalam) appears only in out-of-taxonomy text and is not supported.")

with tab3:
    r, c = esc["record_level"], esc["case_level"]
    st.markdown("**Escalation precision = true actionable escalations / all escalations**")
    ui.metric_row([
        ("Record-level precision", f"{r['escalation_precision']:.1%}", f"{r['true_actionable_escalations']:,} / {r['escalations']:,}"),
        ("Case-level precision", f"{c['escalation_precision']:.1%}", f"{c['true_actionable_cases']} / {c['escalated_cases']}"),
        ("Recall of true Critical", f"{r['recall_of_true_critical']:.1%}", "reports escalated"),
        ("Recall of policy-category reports", f"{r['recall_of_policy_category_reports']:.1%}", "safety/hygiene/conduct"),
    ])
    st.caption(r["definition"] + " " + c["definition"])
    if c["false_positive_cases"]:
        st.markdown("**Escalated cases judged not truly actionable**")
        st.dataframe(pd.DataFrame(c["false_positive_cases"]), hide_index=True, width="stretch")
    sev = esc["severity_confusion"]
    st.markdown("**Policy severity vs synthetic true severity (records)**")
    st.dataframe(pd.DataFrame(sev["matrix"], index=[f"true {s}" for s in sev["labels"]],
                              columns=[f"assigned {s}" for s in sev["labels"]]), width="stretch")

with tab4:
    ui.metric_row([
        ("Pairwise precision", f"{dd['pairwise_precision']:.3f}", f"{dd['predicted_duplicate_pairs']:,} predicted pairs"),
        ("Pairwise recall", f"{dd['pairwise_recall']:.3f}", f"{dd['true_duplicate_pairs']:,} true pairs"),
        ("Estimated unique incidents", f"{dd['estimated_unique_incidents']:,}", f"true: {dd['true_unique_incidents']:,}"),
        ("Possible duplicates flagged", f"{dd['possible_duplicates_flagged']:,}",
         f"{dd['possible_duplicates_truly_duplicate']:.0%} truly duplicates"),
    ])
    st.caption("Deduplication is deliberately conservative: precision is favoured over recall, so unique incidents are "
               "over- rather than under-estimated. Uncertain matches are shown as possible duplicates, not merged.")

with tab5:
    if not det:
        ui.empty_state("Detection replay was skipped.")
    else:
        st.caption(f"Rolling replay over {det['as_of_days_replayed']} as-of days from {det['evaluable_from']}: each day the "
                   f"detector only sees data up to that day (no look-ahead). {det['cells_per_day']:,} store × issue cells/day.")
        pt = pd.DataFrame(det["planted_trends"]).T
        st.dataframe(pt[["name", "store_id", "onset", "detected", "detection_time", "detection_delay_days",
                         "first_watch_delay_days", "naive_first_delay_days", "reports_before_detection",
                         "total_reports"]].rename(columns={
            "name": "Scenario", "store_id": "Store", "onset": "Onset", "detected": "Detected",
            "detection_time": "Confirmed flag", "detection_delay_days": "Delay (days)",
            "first_watch_delay_days": "Watch after (days)", "naive_first_delay_days": "Naive top-10 after (days)",
            "reports_before_detection": "Reports before flag", "total_reports": "Total reports"}), width="stretch")
        nb = det["naive_top10_baseline"]
        ui.metric_row([
            ("StorePulse flag-day precision", f"{det['storepulse_flag_day_precision']:.1%}",
             f"{det['storepulse_flag_days']} confirmed flag-days"),
            ("Naive top-10 volume precision", f"{nb['flag_day_precision']:.1%}", f"{nb['flag_days']:,} flag-days"),
            ("Chronic store (N1) flagged", f"{det['negative_control_N1_flag_days']} days",
             f"naive ranking: {nb['N1_chronic_store_flag_days']} days"),
            ("Seasonal AC (N2) stores flagged", f"{det['negative_control_N2_ac_stores_flagged']}", "network trend adjusted"),
        ])
        st.markdown("**Unplanted flag episodes (counted as false positives) with ground-truth diagnosis**")
        st.dataframe(pd.DataFrame(det["false_positive_details"]), hide_index=True, width="stretch")
        with st.expander("Definitions"):
            for k, v in det["definitions"].items():
                st.markdown(f"- **{k}**: {v}")

st.markdown("#### Limitations of this evaluation")
for item in report["limitations"]:
    st.markdown(f"- {item}")
