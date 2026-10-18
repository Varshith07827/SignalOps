"""Feedback Explorer: search and filter every record; explain why a category was assigned."""
import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src import ui
from src.preprocessing import LANGUAGE_NAMES
from src.taxonomy import SEVERITY_LEVELS, category_label

ui.header("Feedback Explorer", "Search the original feedback and see how each record was interpreted.")
ui.synthetic_banner()
data = ui.require_data()
if data is None:
    st.stop()
fb = data["feedback"]

PRESETS = {
    "All records": {},
    "Hinglish examples": {"language": ["hi-Latn"]},
    "Regional-language examples": {"language": ["ta", "te", "mr", "bn", "kn"]},
    "Unclassified (review required)": {"decision": ["unknown"]},
    "Critical policy escalations": {"severity": ["Critical"]},
}
preset = st.radio("Quick views", list(PRESETS), horizontal=True, key="explorer_preset")
p = PRESETS[preset]

with st.container(border=True):
    c1, c2, c3 = st.columns([2, 1.2, 1.2])
    query = c1.text_input("Search text, feedback ID or cluster ID", placeholder="e.g. chiller, paisa kat, FB039")
    dmin, dmax = fb["timestamp"].min().date(), fb["timestamp"].max().date()
    dates = c2.date_input("Date range", value=(dmax - pd.Timedelta(days=13), dmax), min_value=dmin, max_value=dmax)
    regions = c3.multiselect("Region", sorted(fb["region"].unique()))
    c4, c5, c6, c7 = st.columns(4)
    store_opts = fb[["store_id", "store_name"]].drop_duplicates().sort_values("store_id")
    stores = c4.multiselect("Store", store_opts["store_id"],
                            format_func=lambda s: f"{s} · {store_opts.set_index('store_id').loc[s, 'store_name']}")
    channels = c5.multiselect("Channel", config.CHANNELS, format_func=config.CHANNEL_LABELS.get)
    cats = c6.multiselect("Predicted category", sorted(fb["pred_category"].unique(), key=category_label),
                          format_func=category_label)
    sevs = c7.multiselect("Severity", SEVERITY_LEVELS, default=p.get("severity", []))

view = fb
if isinstance(dates, tuple) and len(dates) == 2:
    view = view[(view["timestamp"].dt.date >= dates[0]) & (view["timestamp"].dt.date <= dates[1])]
if query:
    q = query.strip().lower()
    view = view[view["original_text"].str.lower().str.contains(q, regex=False)
                | view["feedback_id"].str.lower().eq(q) | view["cluster_id"].str.lower().eq(q)
                | view["normalised_text"].str.contains(q, regex=False)]
for col, values in (("region", regions), ("store_id", stores), ("channel", channels),
                    ("pred_category", cats), ("policy_severity", sevs),
                    ("language_hint", p.get("language")), ("decision", p.get("decision"))):
    if values:
        view = view[view[col].isin(values)]
view = view.sort_values("timestamp", ascending=False)

st.caption(f"{len(view):,} matching records · {view['cluster_id'].nunique():,} estimated unique incidents"
           + (" · showing the 1,500 most recent" if len(view) > 1500 else ""))
if view.empty:
    ui.empty_state("No feedback matches these filters. Widen the date range or clear a filter.")
    st.stop()

shown = view.head(1500)
table = pd.DataFrame({
    "ID": shown["feedback_id"],
    "Time": shown["timestamp"].dt.strftime("%d %b %H:%M"),
    "Store": shown["store_id"],
    "Channel": shown["channel"].map(config.CHANNEL_LABELS),
    "Original feedback": shown["original_text"],
    "Predicted category": shown["category_label"],
    "Confidence": shown["confidence"],
    "Review status": shown["decision_label"],
    "Severity": shown["policy_severity"].map(ui.severity_text),
    "Incident": shown["cluster_id"] + shown["dup_status"].map(
        {"unique": "", "merged duplicate": " (dup)", "possible duplicate": " (possible dup)"}),
})
event = st.dataframe(table, hide_index=True, width="stretch", height=380, on_select="rerun",
                     selection_mode="single-row", key="explorer_table", column_config={
                         "Original feedback": st.column_config.TextColumn(width="large"),
                         "Confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})
rows = event.selection.rows if event and event.selection else []
rec = shown.iloc[rows[0]] if rows else shown.iloc[0]
if not rows:
    st.caption("Select a row to inspect it. Showing the most recent record.")

# --------------------------------------------------------------------------- record detail
st.markdown(f"#### Why was {rec['feedback_id']} classified this way?")
exp = ui.classifier().explain(rec["original_text"])
left, right = st.columns([1.2, 1])
with left:
    st.markdown(ui.quote(rec["original_text"], f"{config.CHANNEL_LABELS[rec['channel']]} · {rec['store_name']} "
                         f"({rec['store_id']}, {rec['region']}) · {rec['timestamp']:%d %b %Y %H:%M}"
                         + (f" · rating {int(rec['rating'])}/5" if pd.notna(rec["rating"]) else "")),
                unsafe_allow_html=True)
    st.markdown(f"<div class='sp-kv'><b>Normalised text</b> (original kept unchanged for audit): "
                f"<code>{html.escape(exp['normalised_text'])}</code></div>", unsafe_allow_html=True)
    lang = LANGUAGE_NAMES.get(rec["language_hint"], rec["language_hint"])
    gloss = exp["glossary_matches"]
    st.markdown(f"<div class='sp-kv'><b>Language hint</b> (glossary-based heuristic): {html.escape(lang)}</div>",
                unsafe_allow_html=True)
    if gloss:
        st.markdown(" ".join(f"<span class='sp-chip'>{html.escape(g['matched'])} → {html.escape(g['gloss'])}</span>"
                             for g in gloss), unsafe_allow_html=True)
    st.markdown(f"<div class='sp-kv'><b>Decision</b>: {html.escape(rec['decision_label'])} — "
                f"{html.escape(rec['decision_reason'])} (hybrid confidence {rec['confidence']:.2f}, "
                f"model-only {rec['ml_confidence']:.2f}, known vocabulary {rec['known_token_share']:.0%})</div>",
                unsafe_allow_html=True)
    st.markdown(f"<div class='sp-kv'><b>Rule evidence</b>: {html.escape(rec['rule_hits'] or 'no keyword rules fired')}</div>",
                unsafe_allow_html=True)
    if exp["top_word_features"]:
        st.markdown("<div class='sp-kv'><b>Terms that pushed the model towards "
                    f"{html.escape(category_label(exp['prediction']['candidate_category']))}</b></div>"
                    + " ".join(f"<span class='sp-chip'>{html.escape(t)} +{w:.2f}</span>"
                               for t, w in exp["top_word_features"]), unsafe_allow_html=True)
with right:
    top3 = [t.split("=") for t in rec["top3"].split("; ")]
    fig = go.Figure(go.Bar(x=[float(v) for _, v in top3][::-1], y=[category_label(c) for c, _ in top3][::-1],
                           orientation="h", marker=dict(color=ui.SERIES[0], cornerradius=4),
                           hovertemplate="%{y}: %{x:.2f}<extra></extra>"))
    fig.update_layout(title=dict(text="Top-3 candidate categories (hybrid probability)", font=dict(size=13)),
                      xaxis=dict(range=[0, 1]))
    st.plotly_chart(ui.style_fig(fig, 200, legend=False), width="stretch")
    st.markdown(f"{ui.severity_badge(rec['policy_severity'])} {ui.badge(rec['verification_status'], '#8C97AB')}"
                f"{ui.badge('Action required' if rec['requires_action'] else 'No action', '#4FB3BF')}",
                unsafe_allow_html=True)
    st.markdown(f"<div class='sp-kv'><b>Severity reasoning</b>: {html.escape(rec['severity_reason'])}</div>"
                f"<div class='sp-kv'><b>Escalation</b>: {html.escape(rec['policy_escalation'])} · "
                f"<b>Owner</b>: {html.escape(rec['owner'])}"
                + (f" (with {html.escape(rec['secondary_owner'])})" if rec["secondary_owner"] else "") + "</div>",
                unsafe_allow_html=True)
    members = fb[fb["cluster_id"] == rec["cluster_id"]].sort_values("timestamp")
    st.markdown(f"<div class='sp-kv'><b>Incident grouping</b>: {rec['cluster_id']} · {rec['dup_status']} · "
                f"{len(members)} report(s) in this incident</div>", unsafe_allow_html=True)
    if rec["possible_duplicate_of"]:
        st.caption(f"Possible duplicate of {rec['possible_duplicate_of']} (score {rec['dup_score']:.2f}) — not merged "
                   "because confidence was insufficient.")
    for m in members.itertuples():
        if m.feedback_id != rec["feedback_id"]:
            st.markdown(ui.quote(m.original_text, f"{m.feedback_id} · {config.CHANNEL_LABELS[m.channel]} · "
                                 f"{m.timestamp:%d %b %H:%M}"), unsafe_allow_html=True)
