"""Emerging Issues: store x issue signals rising faster than their baseline, with evidence."""
import html
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src import ui
from src.anomaly_detection import network_movements

ui.header("Emerging Issues", "Which store-level problems are rising unusually fast — not just which are biggest?")
ui.synthetic_banner()
data = ui.require_data()
if data is None:
    st.stop()
fb, signals, cases = data["feedback"], data["signals"], ui.cases_with_state(data["cases"])
as_of = pd.Timestamp(data["meta"]["as_of"])

if signals.empty:
    ui.empty_state("No emerging or watch-level signals at this as-of date. The detector only flags a store/issue "
                   "when it rises well above its own baseline and the network trend.")
    st.stop()

trend_cases = cases[cases["case_type"].str.startswith("Emerging")].set_index(["store_id", "category"])
sig = signals.copy()
keys = list(zip(sig["store_id"], sig["category"]))
sig["case_id"] = [trend_cases["case_id"].get(k, "") for k in keys]
sig["priority_score"] = [trend_cases["priority_score"].get(k, float("nan")) for k in keys]
sig["case_severity"] = [trend_cases["severity"].get(k, s) for k, s in zip(keys, sig["severity"])]
sig["status"] = [trend_cases["status"].get(k, "—") for k in keys]
sig = sig.sort_values(["flagged", "priority_score", "p_value"], ascending=[False, False, True]).reset_index(drop=True)

n_flag = int(sig["flagged"].sum())
st.caption(f"As of {as_of.date()} · {n_flag} confirmed emerging signal(s) · {len(sig) - n_flag} on watch "
           "(notable but not confirmed; not escalated). Ranked by operational priority.")

table = pd.DataFrame({
    "Rank": range(1, len(sig) + 1),
    "Signal": sig["signal"],
    "Store": sig["store_name"] + " (" + sig["store_id"] + ")",
    "Region": sig["region"],
    "Issue": sig["category_label"],
    "Baseline / wk": sig["baseline_weekly_mean"],
    "Last 7 days": sig["current_count"],
    "Expected": sig["expected_count"],
    "Window": sig["window_count"].astype(str) + " in " + sig["evidence_window_days"].astype(str) + "d",
    "Rate ratio": sig["rate_ratio"],
    "p (corrected)": sig["p_value"],
    "Severity": sig["case_severity"].map(ui.severity_text),
    "Owner": sig["owner"],
    "Priority": sig["priority_score"],
})
event = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                     key="emerging_table", column_config={
                         "Baseline / wk": st.column_config.NumberColumn(format="%.2f"),
                         "Expected": st.column_config.NumberColumn(format="%.2f",
                                                                   help="Expected unique incidents in the evidence window"),
                         "Rate ratio": st.column_config.NumberColumn(format="%.1f×"),
                         "p (corrected)": st.column_config.NumberColumn(format="%.1e"),
                         "Priority": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f")})
rows = event.selection.rows if event and event.selection else []
s = sig.iloc[rows[0] if rows else 0]
if not rows:
    st.caption("Click a row to open its evidence. Showing the top-ranked signal.")

# --------------------------------------------------------------------------- evidence panel
st.markdown(f"#### {s['category_label']} · {s['store_name']} ({s['store_id']}, {s['region']})")
st.markdown(f"{ui.badge(s['signal'], '#4FB3BF' if s['flagged'] else '#8C97AB')}{ui.severity_badge(s['case_severity'])}"
            f"{ui.badge('Owner: ' + s['owner'], '#C9D2E0')}"
            + (ui.badge(s['case_id'], '#8C97AB') if s["case_id"] else ""), unsafe_allow_html=True)
evidence_ids = json.loads(s["evidence_ids"]) if isinstance(s["evidence_ids"], str) else list(s["evidence_ids"])
ev = fb[fb["feedback_id"].isin(evidence_ids)].sort_values("timestamp")
ui.metric_row([
    ("Historical baseline", f"{s['baseline_weekly_mean']:.2f}/wk", f"{s['baseline_weeks']} weeks before the window"),
    ("Current (7 days)", f"{s['current_count']}", f"{s['current_reports']} reports · {ev['cluster_id'].nunique()} unique"),
    ("Relative change", f"{s['relative_change']:+.0%}", f"{s['window_count']} vs {s['expected_count']:.2f} expected "
                                                         f"({s['evidence_window_days']}d)"),
    ("Statistical evidence", f"p={s['p_value']:.1e}", f"BH q={s['q_value']:.1e} · z={s['z_score']:.1f}"),
    ("Detected", f"{pd.Timestamp(s['detection_time']):%d %b %Y}", f"as-of {pd.Timestamp(s['detection_time']):%H:%M}, "
                                                                  "data up to this time only"),
])
st.markdown("")
c1, c2 = st.columns([1.25, 1])
with c1:
    hist = fb[(fb["store_id"] == s["store_id"]) & (fb["pred_category"] == s["category"]) & fb["is_cluster_anchor"]]
    hist = hist[hist["timestamp"] > as_of - pd.Timedelta(weeks=16)]
    weeks_back = ((as_of + pd.Timedelta(days=1) - hist["timestamp"]).dt.days // 7)
    counts = weeks_back.value_counts().reindex(range(16), fill_value=0).sort_index(ascending=False)
    week_end = [as_of - pd.Timedelta(weeks=int(w)) for w in counts.index]
    colors = [ui.SERIES[1] if w == 0 else ui.SERIES[0] for w in counts.index]
    fig = go.Figure(go.Bar(x=week_end, y=counts.values, marker=dict(color=colors, cornerradius=4),
                           name="Unique incidents", hovertemplate="Week ending %{x|%d %b}: %{y}<extra></extra>"))
    fig.add_hline(y=s["baseline_eb"], line=dict(color="#C9D2E0", dash="dot", width=1.5),
                  annotation_text=f"baseline {s['baseline_eb']:.2f}/wk", annotation_font_color="#C9D2E0")
    fig.update_layout(title=dict(text="Weekly unique incidents at this store (current week highlighted)",
                                 font=dict(size=13)), bargap=0.25)
    st.plotly_chart(ui.style_fig(fig, 300, legend=False), width="stretch")
    st.markdown(f"<div class='sp-kv'><b>Why flagged</b>: {html.escape(s['explanation'])}</div>",
                unsafe_allow_html=True)
with c2:
    st.markdown("<div class='sp-kv'><b>Recommended action</b></div>", unsafe_allow_html=True)
    st.info(s["recommended_action"])
    ch = ev["channel"].map(config.CHANNEL_LABELS).value_counts()
    st.markdown("<div class='sp-kv'><b>Reporting channels</b> (independent channels strengthen credibility)</div>"
                + " ".join(f"<span class='sp-chip'>{html.escape(k)}: {v}</span>" for k, v in ch.items()),
                unsafe_allow_html=True)
    st.markdown(f"<div class='sp-kv'><b>Network trend adjustment</b>: ×{s['network_ratio']:.2f} · "
                f"<b>Store volume adjustment</b>: ×{s['exposure_ratio']:.2f} · "
                f"<b>Persistence</b>: {s['persistence_weeks']}/4 weeks elevated</div>", unsafe_allow_html=True)
    st.caption("A signal is evidence of an unusual pattern, not proof of a verified incident.")

st.markdown(f"##### Supporting feedback ({len(ev)} reports in the last 7 days)")
for r in ev.itertuples():
    st.markdown(ui.quote(r.original_text, f"{r.feedback_id} · {config.CHANNEL_LABELS[r.channel]} · "
                         f"{r.timestamp:%a %d %b %H:%M} · incident {r.cluster_id} ({r.dup_status}) · "
                         f"confidence {r.confidence:.2f}"), unsafe_allow_html=True)

with st.expander("Network-wide movements (category level, last 4 weeks)"):
    st.caption("Category totals across all stores. Network-wide changes (e.g. seasonal AC complaints) are handled "
               "by the network-trend adjustment rather than flagged at every store.")
    nm = network_movements(fb, as_of)
    nm.columns = [f"w/e {c:%d %b}" for c in nm.columns]
    nm["Change vs prior week"] = nm.iloc[:, -1] - nm.iloc[:, -2]
    st.dataframe(nm.sort_values(nm.columns[-2], ascending=False), width="stretch")

with st.expander("How the detector works"):
    st.markdown("""
1. Counts **estimated unique incidents** per store × issue (duplicates and possible duplicates are not counted twice).
2. Builds a **12-week baseline** strictly before the window, shrunk towards the category's network share × the
   store's own feedback volume (empirical Bayes) so stores of different size are comparable.
3. Adjusts the expectation for changes in the store's **overall reporting volume** and the category's
   **network-wide trend** (leave-one-out), so seasonal or network-wide rises are not mistaken for store problems.
4. Tests 7- and 14-day windows with a **negative-binomial tail probability** (over-dispersion estimated from
   history), Bonferroni-corrected across windows, then **Benjamini–Hochberg** across all store × issue cells.
5. Requires **minimum evidence**: ≥3 unique incidents, ≥2 above expectation and ≥2× the expected rate.
   Percentage growth alone never raises a flag.
""")
