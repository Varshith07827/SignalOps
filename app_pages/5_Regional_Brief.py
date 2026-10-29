"""Regional Brief: one-page weekly action brief per region, exportable as HTML or CSV."""
import html

import pandas as pd
import streamlit as st

from src import reporting, storage, ui

ui.header("Regional Brief", "A one-page weekly action brief for each region's operations manager.")
ui.synthetic_banner()
data = ui.require_data()
if data is None:
    st.stop()
fb, cases, signals = data["feedback"], data["cases"], data["signals"]

c1, c2 = st.columns([1, 3])
region = c1.selectbox("Region", sorted(fb["region"].unique()))
brief = reporting.build_regional_brief(fb, cases, signals, region, as_of=data["meta"]["as_of"],
                                       case_states=storage.get_case_states())
c2.markdown(f"<div class='sp-sub' style='margin-top:30px'>Reporting week {brief['week']} · "
            f"{brief['kpis']['stores_reporting']} stores reporting</div>", unsafe_allow_html=True)

k = brief["kpis"]
ui.metric_row([
    ("Feedback this week", f"{k['feedback_records']:,}", f"previous week {k['feedback_previous_week']:,}"),
    ("Est. unique incidents", f"{k['estimated_unique_incidents']:,}", "this week"),
    ("High / Critical reports", f"{k['high_or_critical_reports']:,}", "policy severity"),
    ("Open cases", f"{k['open_cases']}", f"{k['p1_cases']} mandatory escalations (P1)"),
])

html_doc = reporting.render_brief_html(brief)
d1, d2, _ = st.columns([1, 1, 2])
d1.download_button("Download brief (HTML)", html_doc, file_name=f"storepulse_brief_{region}_{brief['as_of']}.html",
                   mime="text/html", type="primary", width="stretch",
                   help="Self-contained page; use the browser's Print → Save as PDF for a PDF copy.")
d2.download_button("Download top issues (CSV)", reporting.brief_to_csv(brief),
                   file_name=f"storepulse_brief_{region}_{brief['as_of']}.csv", mime="text/csv", width="stretch")

st.markdown(f"#### Top {len(brief['top_issues'])} priority issues")
if not brief["top_issues"]:
    ui.empty_state("No cases for this region in the reporting week.")
for i, t in enumerate(brief["top_issues"], 1):
    with st.container(border=True):
        delta = t["store_incidents_this_week"] - t["store_incidents_previous_week"]
        st.markdown(f"**{i}. {html.escape(t['category'])}** — {html.escape(t['store'])} &nbsp; "
                    f"{ui.severity_badge(t['severity'])}{ui.badge(t['rank_tier'].split(' - ')[0], '#4FB3BF')}"
                    f"{ui.badge('Owner: ' + t['owner'], '#C9D2E0')}{ui.badge(t['status'], '#8C97AB')}",
                    unsafe_allow_html=True)
        a, b = st.columns([1, 1.4])
        a.markdown(f"<div class='sp-kv'><b>Trend vs previous week</b><br>store {t['store_incidents_previous_week']} → "
                   f"{t['store_incidents_this_week']} ({delta:+d}) · region {t['region_incidents_previous_week']} → "
                   f"{t['region_incidents_this_week']}</div>"
                   f"<div class='sp-kv'><b>Affected stores</b><br>{html.escape(', '.join(t['affected_stores']) or '—')}</div>"
                   f"<div class='sp-kv'><b>Verification</b>: {html.escape(t['verification'])}</div>",
                   unsafe_allow_html=True)
        a.markdown(f"<div class='sp-kv'><b>Recommended action</b><br>{html.escape(t['recommended_action'])}</div>",
                   unsafe_allow_html=True)
        for q in t["quotes"]:
            b.markdown(ui.quote(q["text"], f"{q['id']} · {q['channel']} · {q['time']}"), unsafe_allow_html=True)

st.markdown("#### Emerging incidents in this region")
if brief["emerging"]:
    em = pd.DataFrame(brief["emerging"])
    st.dataframe(em.rename(columns={"signal": "Signal", "store": "Store", "category": "Issue",
                                    "baseline_weekly_mean": "Baseline / wk", "current_count": "Last 7 days",
                                    "window_count": "Window count", "window_days": "Window (days)",
                                    "expected": "Expected", "p_value": "p", "owner": "Owner"}),
                 hide_index=True, width="stretch",
                 column_config={"Baseline / wk": st.column_config.NumberColumn(format="%.2f"),
                                "Expected": st.column_config.NumberColumn(format="%.2f"),
                                "p": st.column_config.NumberColumn(format="%.1e")})
else:
    ui.empty_state("No emerging or watch-level signals in this region this week.")

st.markdown("#### Issue trend vs previous week")
trend = pd.DataFrame(brief["category_trend"]).rename(columns={
    "category": "Issue", "this_week": "This week", "previous_week": "Previous week", "change": "Change"})
st.dataframe(trend, hide_index=True, width="stretch")

with st.expander("Preview the exported HTML brief"):
    # All feedback text in the brief is HTML-escaped by reporting.render_brief_html.
    if hasattr(st, "iframe"):
        st.iframe(html_doc, height=900)
    else:  # Streamlit < 1.50
        st.components.v1.html(html_doc, height=900, scrolling=True)
