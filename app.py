"""StorePulse - Voice-of-Store Intelligence Engine.

Launch with:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

import config
from src import storage, ui

st.set_page_config(page_title="StorePulse", page_icon="📡", layout="wide", initial_sidebar_state="expanded")
ui.apply_style()


def overview() -> None:
    ui.header("StorePulse", "From feedback to foresight — voice-of-store intelligence for retail operations.",
              kicker="Overview")
    ui.synthetic_banner()
    st.markdown(
        "<div class='sp-flow'>" + "<span class='arrow'>→</span>".join(
            f"<span class='step'>{s}</span>" for s in
            ["Feedback", "Classification", "Deduplication", "Severity", "Trend detection", "Prioritisation",
             "Ownership", "Action brief"]) + "</div>", unsafe_allow_html=True)

    meta = storage.read_meta() if ui.data_ready() else {}
    if meta:
        ui.metric_row([
            ("Feedback records", f"{meta['n_records']:,}", f"{meta['data_start']} → {meta['data_end']}"),
            ("Estimated unique incidents", f"{meta['n_unique_incidents']:,}", "after conservative deduplication"),
            ("Analysis as of", meta["as_of"], "last day of the synthetic period"),
            ("Last processed", meta["processed_at"].replace("T", " "), f"pipeline ran in {meta['runtime_seconds']}s"),
        ])
    else:
        ui.empty_state("No processed data found. Use 'Run pipeline' below (about a minute on first run).")

    st.markdown("#### Two-minute demo path")
    c1, c2 = st.columns(2)
    with c1:
        st.page_link("app_pages/1_Command_Centre.py", label="1 · Command Centre — network KPIs and top priorities",
                     icon=":material/dashboard:")
        st.page_link("app_pages/2_Feedback_Explorer.py", label="2 · Feedback Explorer — multilingual classification",
                     icon=":material/manage_search:")
        st.page_link("app_pages/3_Emerging_Issues.py", label="3 · Emerging Issues — refrigeration & payment trends",
                     icon=":material/trending_up:")
        st.page_link("app_pages/4_Incident_Management.py", label="4 · Incident Management — allergen escalation",
                     icon=":material/assignment:")
    with c2:
        st.page_link("app_pages/5_Regional_Brief.py", label="5 · Regional Brief — weekly action brief export",
                     icon=":material/description:")
        st.page_link("app_pages/6_Model_Evaluation.py", label="6 · Model Evaluation — synthetic ground truth",
                     icon=":material/analytics:")
        st.caption("Scenario stores and narration are listed in DEMO_GUIDE.md.")

    st.markdown("#### Data and model controls")
    st.caption("Everything runs locally. Regenerating is deterministic: the same seed reproduces the same "
               "records and planted scenarios. Case workflow state is stored separately and survives re-processing.")
    b1, b2, b3, b4 = st.columns(4)
    action = None
    if b1.button("Run pipeline", help="Process existing data (generates data and trains the model if missing)",
                 width="stretch", type="primary"):
        action = {}
    if b2.button("Retrain model + run", width="stretch"):
        action = {"retrain": True}
    if b3.button("Regenerate data + run", width="stretch",
                 help=f"Recreate {config.GENERATOR.n_records:,} synthetic records (seed {config.GENERATOR.seed})"):
        action = {"regenerate": True}
    if b4.button("Reset case workflow state", width="stretch"):
        storage.reset_state()
        st.success("Case statuses, owners and verification states reset.")
    if action is not None:
        from src.pipeline import run_pipeline
        with st.spinner("Running pipeline: classification, severity, deduplication, detection, prioritisation ..."):
            out = run_pipeline(verbose=False, **action)
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success(f"Processed {out['meta']['n_records']:,} records in {out['meta']['runtime_seconds']}s; "
                   f"{len(out['cases'])} cases as of {out['meta']['as_of']}.")
        st.rerun()

    with st.expander("How StorePulse works"):
        st.markdown("""
- **Classification** — text normalisation (typos, abbreviations, emojis, a documented Hinglish/regional glossary)
  then keyword rules + TF-IDF logistic regression. Low-confidence or out-of-vocabulary feedback is left
  *unclassified* for human review instead of being forced into a category.
- **Severity policy** — deterministic rules: allergen, food-safety, hygiene/pest, physical-safety and
  staff-misconduct allegations receive High/Critical treatment from a *single* report. Severity, classifier
  confidence, verification status and required action are tracked separately.
- **Deduplication** — conservative: same store + same predicted category + within 36h of the first report +
  text/entity/time similarity. Uncertain matches are flagged as *possible duplicates*, never silently merged.
- **Emerging issues** — store × category counts of unique incidents compared with an empirical-Bayes baseline,
  adjusted for store volume and network trend, tested with a negative-binomial tail probability over 7- and
  14-day windows with false-discovery control. Percentage growth alone never raises a flag.
- **Prioritisation** — policy-mandated escalations (P1) always rank above ordinary scoring; within a tier a
  0–100 score combines severity, evidence, trend, breadth and persistence. Ownership mapping is provisional.
""")


# Pages live in app_pages/ (not pages/): a folder named pages/ triggers Streamlit's legacy
# auto-discovery, which can bypass st.navigation when a page URL is the first request.
pages = [
    st.Page(overview, title="Overview", icon=":material/home:", default=True),
    st.Page("app_pages/1_Command_Centre.py", url_path="Command_Centre", title="Command Centre", icon=":material/dashboard:"),
    st.Page("app_pages/2_Feedback_Explorer.py", url_path="Feedback_Explorer", title="Feedback Explorer", icon=":material/manage_search:"),
    st.Page("app_pages/3_Emerging_Issues.py", url_path="Emerging_Issues", title="Emerging Issues", icon=":material/trending_up:"),
    st.Page("app_pages/4_Incident_Management.py", url_path="Incident_Management", title="Incident Management", icon=":material/assignment:"),
    st.Page("app_pages/5_Regional_Brief.py", url_path="Regional_Brief", title="Regional Brief", icon=":material/description:"),
    st.Page("app_pages/6_Model_Evaluation.py", url_path="Model_Evaluation", title="Model Evaluation", icon=":material/analytics:"),
]
nav = st.navigation(pages)
with st.sidebar:
    st.markdown("**StorePulse**  \n<span style='color:#8C97AB;font-size:0.8rem'>From feedback to foresight</span>",
                unsafe_allow_html=True)
    st.caption("Synthetic demonstration data · provisional taxonomy " + "· local only")
nav.run()
