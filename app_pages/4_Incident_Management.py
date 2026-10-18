"""Incident Management: case evidence, workflow status, ownership and verification state."""
import html
import json

import pandas as pd
import streamlit as st

import config
from src import storage, ui
from src.routing import valid_owners
from src.taxonomy import POLICY_RULE_BY_ID

ui.header("Incident Management", "Work the case queue: review evidence, assign owners and record verification.")
ui.synthetic_banner("Statuses you set here are saved locally in data/state/case_state.duckdb.")
data = ui.require_data()
if data is None:
    st.stop()
fb = data["feedback"]
cases = ui.cases_with_state(data["cases"])
if cases.empty:
    ui.empty_state("No cases for the current reporting week.")
    st.stop()

with st.container(border=True):
    c1, c2, c3, c4, c5 = st.columns([1.6, 1, 1, 1, 1])
    query = c1.text_input("Search case, store or issue", placeholder="e.g. allergen, S013, POL-")
    tiers = c2.multiselect("Tier", sorted(cases["tier_label"].unique()))
    regions = c3.multiselect("Region", sorted(cases["region"].unique()))
    owners = c4.multiselect("Owner", sorted(cases["assigned_owner"].unique()))
    statuses = c5.multiselect("Status", config.CASE_STATUSES)

view = cases
if query:
    q = query.lower()
    view = view[view["case_id"].str.lower().str.contains(q, regex=False)
                | view["store_id"].str.lower().str.contains(q, regex=False)
                | view["store_name"].str.lower().str.contains(q, regex=False)
                | view["category_label"].str.lower().str.contains(q, regex=False)
                | view["category"].str.contains(q, regex=False)]
for col, vals in (("tier_label", tiers), ("region", regions), ("assigned_owner", owners), ("status", statuses)):
    if vals:
        view = view[view[col].isin(vals)]

counts = cases["status"].value_counts()
st.caption(f"{len(view)} of {len(cases)} cases · " + " · ".join(f"{s}: {counts.get(s, 0)}" for s in config.CASE_STATUSES))
if view.empty:
    ui.empty_state("No cases match these filters.")
    st.stop()

table = pd.DataFrame({
    "Case": view["case_id"], "Tier": view["tier_label"].str.split(" - ").str[0], "Score": view["priority_score"],
    "Severity": view["severity"].map(ui.severity_text), "Issue": view["category_label"],
    "Store": view["store_name"] + " (" + view["store_id"] + ")", "Type": view["case_type"],
    "Reports": view["n_reports"], "Owner": view["assigned_owner"], "Status": view["status"],
    "Verification": view["verification"],
})
event = st.dataframe(table, hide_index=True, width="stretch", height=320, on_select="rerun",
                     selection_mode="single-row", key="case_table", column_config={
                         "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f")})
rows = event.selection.rows if event and event.selection else []
case = view.iloc[rows[0] if rows else 0]
if not rows:
    st.caption("Select a case to open it. Showing the highest-priority case.")

# --------------------------------------------------------------------------- case detail
st.markdown(f"#### {case['case_id']} · {case['category_label']} at {case['store_name']}")
st.markdown(ui.severity_badge(case["severity"]) + ui.badge(case["tier_label"], "#4FB3BF")
            + ui.badge(case["escalation"], "#C9D2E0") + ui.badge(case["case_type"], "#8C97AB"),
            unsafe_allow_html=True)

states = config.VERIFICATION_STATES
st.markdown("<div class='sp-kv' style='margin-top:8px'><b>Verification state</b> — an allegation is a report; an "
            "investigation is under way; only a verified incident has been confirmed by the business.</div>"
            "<div class='sp-state'>" + "".join(
                f"<div class='{'on' if s == case['verification'] else ''}'>{html.escape(s)}</div>" for s in states)
            + "</div>", unsafe_allow_html=True)

left, right = st.columns([1.35, 1])
with left:
    st.markdown(f"<div class='sp-kv'><b>Why this priority</b>: {html.escape(case['explanation'])}</div>",
                unsafe_allow_html=True)
    comps = json.loads(case["priority_components"])
    st.markdown(" ".join(f"<span class='sp-chip'>{k}: {v:.2f}</span>" for k, v in comps.items()),
                unsafe_allow_html=True)
    if case["policy_rules"]:
        for rid in case["policy_rules"].split(","):
            rule = POLICY_RULE_BY_ID.get(rid)
            if rule:
                st.markdown(f"<div class='sp-kv'><b>{rid}</b> — {html.escape(rule.name)}: "
                            f"{html.escape(rule.rationale)}</div>", unsafe_allow_html=True)
    if pd.notna(case["current_count"]):
        st.markdown(f"<div class='sp-kv'><b>Trend</b>: {int(case['current_count'])} incidents in 7 days vs "
                    f"{case['baseline_weekly_mean']:.2f}/week baseline (q={case['q_value']:.1e})</div>",
                    unsafe_allow_html=True)
    st.markdown("<div class='sp-kv'><b>Recommended action</b></div>", unsafe_allow_html=True)
    st.info(case["recommended_action"])
    ids = json.loads(case["evidence_ids"])
    ev = fb[fb["feedback_id"].isin(ids)].sort_values("timestamp")
    st.markdown(f"##### Evidence ({len(ev)} report(s), {ev['cluster_id'].nunique()} estimated incident(s))")
    for r in ev.head(25).itertuples():
        st.markdown(ui.quote(r.original_text, f"{r.feedback_id} · {config.CHANNEL_LABELS[r.channel]} · "
                             f"{r.timestamp:%a %d %b %H:%M} · {r.policy_severity} · rules: {r.policy_rules or '—'}"),
                    unsafe_allow_html=True)
    if len(ev) > 25:
        st.caption(f"{len(ev) - 25} more reports not shown; see Feedback Explorer.")

with right:
    with st.form(f"update_{case['case_id']}"):
        st.markdown("**Update case**")
        status = st.selectbox("Status", config.CASE_STATUSES, index=config.CASE_STATUSES.index(case["status"]))
        owner_opts = valid_owners()
        owner = st.selectbox("Owner", owner_opts, index=owner_opts.index(case["assigned_owner"])
                             if case["assigned_owner"] in owner_opts else 0,
                             help=f"Suggested by provisional routing: {case['owner']}"
                                  + (f" (secondary: {case['secondary_owner']})" if case["secondary_owner"] else ""))
        verification = st.selectbox("Verification state", states, index=states.index(case["verification"]))
        note = st.text_area("Note", placeholder="e.g. Batch withdrawn pending supplier label check", height=80)
        submitted = st.form_submit_button("Save", type="primary", width="stretch")
    if submitted:
        storage.update_case(case["case_id"], status=status, owner=owner, verification=verification,
                            note=note or None)
        st.toast(f"Saved {case['case_id']}")
        st.rerun()
    if case["note"]:
        st.markdown(f"<div class='sp-kv'><b>Latest note</b>: {html.escape(case['note'])}</div>", unsafe_allow_html=True)
    hist = storage.case_history(case["case_id"])
    st.markdown("**Audit trail**")
    if hist.empty:
        st.caption("No changes yet — this case is New and the allegation is unverified.")
    else:
        st.dataframe(hist[["event_time", "field", "old_value", "new_value", "note"]].sort_values(
            "event_time", ascending=False), hide_index=True, width="stretch")
