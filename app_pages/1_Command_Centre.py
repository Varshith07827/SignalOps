"""Command Centre: network KPIs, weekly trends, regional distribution, top priorities."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import ui
from src.taxonomy import SEVERITY_RANK, category_label

ui.header("Command Centre", "What needs attention across the network this week?")
ui.synthetic_banner()
data = ui.require_data()
if data is None:
    st.stop()

fb, cases, signals = data["feedback"], ui.cases_with_state(data["cases"]), data["signals"]
as_of = pd.Timestamp(data["meta"]["as_of"])
week_lo = as_of - pd.Timedelta(days=6)
this_week = fb[fb["timestamp"] >= week_lo]
prev_week = fb[(fb["timestamp"] >= week_lo - pd.Timedelta(days=7)) & (fb["timestamp"] < week_lo)]
high_cases = cases[cases["severity"].map(SEVERITY_RANK) >= SEVERITY_RANK["High"]]
emerging = signals[signals["flagged"]] if len(signals) else signals
awaiting = cases[cases["status"].isin(["New", "Under Review"])]

st.caption(f"Reporting week {week_lo.date()} → {as_of.date()} · all figures computed from the processed synthetic dataset")
ui.metric_row([
    ("Feedback processed", f"{len(fb):,}", f"{len(this_week):,} this week (prev. {len(prev_week):,})",
     "All feedback records processed by the pipeline across the full synthetic period."),
    ("Est. unique incidents", f"{fb['cluster_id'].nunique():,}",
     f"{this_week['cluster_id'].nunique():,} this week · {len(fb) - fb['cluster_id'].nunique():,} duplicates merged",
     "Records grouped into canonical incidents by conservative deduplication."),
    ("High-severity cases", f"{len(high_cases):,}", f"{(cases['tier'] == 1).sum()} Critical policy escalations (P1)",
     "Open cases this week with High or Critical policy severity."),
    ("Emerging incidents", f"{len(emerging)}", "store-level trends above baseline",
     "Confirmed store x issue signals from the emerging-issue detector."),
    ("Escalations awaiting review", f"{len(awaiting):,}", "status New or Under Review",
     "Escalated cases whose workflow status is still New or Under Review."),
])

st.markdown("")
left, right = st.columns([1.15, 1])

with left:
    st.markdown("##### Weekly issue trends")
    st.caption("Estimated unique incidents per week. Which operational issues are growing network-wide?")
    weekly = (fb[fb["is_cluster_anchor"] & ~fb["pred_category"].isin(["no_issue", "unclassified"])]
              .groupby(["week_start", "pred_category"])["cluster_id"].nunique().reset_index(name="incidents"))
    recent = weekly[weekly["week_start"] >= weekly["week_start"].max() - pd.Timedelta(weeks=3)]
    default = recent.groupby("pred_category")["incidents"].sum().nlargest(5).index.tolist()
    options = sorted(weekly["pred_category"].unique(), key=category_label)
    chosen = st.multiselect("Issues (max 6)", options, default=default, max_selections=6,
                            format_func=category_label, label_visibility="collapsed")
    fig = go.Figure()
    for i, cat in enumerate(chosen):
        s = weekly[weekly["pred_category"] == cat]
        fig.add_trace(go.Scatter(x=s["week_start"], y=s["incidents"], name=category_label(cat), mode="lines",
                                 line=dict(width=2, color=ui.SERIES[i]),
                                 hovertemplate="%{x|%d %b}: %{y} incidents<extra>" + category_label(cat) + "</extra>"))
    fig.update_layout(hovermode="x unified", yaxis_title="Unique incidents / week")
    if chosen:
        st.plotly_chart(ui.style_fig(fig, 340), width="stretch")
    else:
        ui.empty_state("Select at least one issue to plot.")

with right:
    st.markdown("##### Issue distribution by region")
    st.caption("Incidents per 1,000 feedback records, last 4 weeks — normalised so large regions don't dominate.")
    last4 = fb[fb["timestamp"] >= as_of - pd.Timedelta(days=27)]
    inc = last4[last4["is_cluster_anchor"] & ~last4["pred_category"].isin(["no_issue", "unclassified"])]
    top_cats = inc["pred_category"].value_counts().head(12).index
    piv = (inc[inc["pred_category"].isin(top_cats)].groupby(["region", "pred_category"]).size().unstack(fill_value=0))
    rate = piv.div(last4.groupby("region").size(), axis=0) * 1000
    rate = rate[top_cats]
    heat = go.Figure(go.Heatmap(
        z=rate.values.round(1), x=[category_label(c) for c in rate.columns], y=rate.index,
        colorscale=ui.SEQUENTIAL, xgap=2, ygap=2, colorbar=dict(title="per 1k", thickness=10),
        hovertemplate="%{y} · %{x}<br>%{z} incidents per 1,000 feedback<extra></extra>"))
    heat.update_xaxes(tickangle=-35, showgrid=False)
    heat.update_yaxes(showgrid=False)
    st.plotly_chart(ui.style_fig(heat, 375, legend=False), width="stretch")

st.markdown("##### Highest-priority operational problems")
st.caption("Policy-mandated escalations (P1) always rank first; within a tier, cases are ordered by the 0–100 "
           "priority score. Every case is an unverified allegation until investigated.")
top = cases.head(12).copy()
top["Severity"] = top["severity"].map(ui.severity_text)
table = top[["tier_label", "priority_score", "Severity", "category_label", "store_name", "region", "case_type",
             "assigned_owner", "status", "n_reports"]].rename(columns={
    "tier_label": "Tier", "priority_score": "Score", "category_label": "Issue", "store_name": "Store",
    "region": "Region", "case_type": "Type", "assigned_owner": "Owner", "status": "Status", "n_reports": "Reports"})
st.dataframe(table, hide_index=True, width="stretch", column_config={
    "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
    "Tier": st.column_config.TextColumn("Tier", width="medium")})

if len(emerging):
    st.markdown("##### Emerging this week")
    trend_sev = (cases[cases["case_type"].str.startswith("Emerging")]
                 .set_index(["store_id", "category"])["severity"].to_dict())
    for s in emerging.itertuples():
        sev = trend_sev.get((s.store_id, s.category), s.severity)
        st.markdown(f"{ui.severity_badge(sev)} **{s.category_label}** at {s.store_name} ({s.store_id}, "
                    f"{s.region}) — {s.current_count} incidents in 7 days vs {s.baseline_weekly_mean:.1f}/week "
                    f"baseline · owner **{s.owner}**", unsafe_allow_html=True)
    st.page_link("app_pages/3_Emerging_Issues.py", label="Open Emerging Issues for evidence", icon=":material/arrow_forward:")
