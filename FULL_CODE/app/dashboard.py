"""Streamlit dashboard: regional briefs, emerging-issue flags, owner queues and a feedback explorer.

    python FULL_CODE/main.py                       # builds FULL_CODE/outputs/ first
    streamlit run FULL_CODE/app/dashboard.py

Presentation only: all logic lives in ``voice_of_store``; this file reads the tables ``main.py`` wrote.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voice_of_store.brief import build_region_brief, render_markdown  # noqa: E402
from voice_of_store.config import load_settings  # noqa: E402
from voice_of_store.data_io import DataValidationError, load_pack  # noqa: E402

SETTINGS = load_settings()
SEVERITY_ORDER = ["critical", "high", "medium", "low"]


@st.cache_data(show_spinner="Loading engine outputs...")
def load_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    outputs = SETTINGS.paths.outputs_dir
    records = pd.read_csv(outputs / "records.csv", parse_dates=["created_at", "week_start"])
    flags = pd.read_csv(outputs / "flags.csv")
    pack = load_pack(SETTINGS.paths.data_dir)
    return records, flags, pack.taxonomy.reset_index(), pack.stores


def week_picker(records: pd.DataFrame) -> pd.Timestamp:
    weeks = sorted((pd.Timestamp(w) for w in records["week_start"].unique()), reverse=True)
    return st.sidebar.selectbox("Week starting", weeks, format_func=lambda w: f"{w:%d %b %Y}")


def show_overview(records: pd.DataFrame, flags: pd.DataFrame, week: pd.Timestamp) -> None:
    this_week = records[records["week_start"] == week]
    actionable = this_week[this_week["actionable"] == 1]
    cols = st.columns(4)
    cols[0].metric("Feedback this week", f"{len(this_week):,}")
    cols[1].metric("Actionable", f"{len(actionable):,}")
    cols[2].metric("High / critical", int(actionable["severity"].isin(["high", "critical"]).sum()))
    cols[3].metric("Emerging flags", int((flags["as_of_week_start"] == f"{week:%Y-%m-%d}").sum()))
    left, right = st.columns(2)
    left.subheader("Actionable issues by owner")
    left.bar_chart(actionable["owner_function"].value_counts())
    right.subheader("Feedback by language")
    right.bar_chart(this_week["language"].value_counts())
    st.subheader("Weekly actionable volume by region")
    trend = records[records["actionable"] == 1].groupby(["week_start", "region"]).size().unstack(fill_value=0)
    st.line_chart(trend)


def show_brief(records, flags, taxonomy, stores, week) -> None:
    regions = sorted(records["region"].unique())
    region = st.selectbox("Region", regions)
    names = dict(zip(stores["store_id"], stores["store_name"], strict=True))
    items = build_region_brief(records, flags, region, week, taxonomy.set_index("issue_type_id"), names, SETTINGS.brief)
    markdown = render_markdown(region, week, items)
    st.markdown(markdown)
    st.download_button("Download brief (Markdown)", markdown, file_name=f"brief_{region}_{week:%Y-%m-%d}.md")


def show_flags(records: pd.DataFrame, flags: pd.DataFrame, stores: pd.DataFrame) -> None:
    st.caption(
        "Each flag is raised causally (only feedback up to that week's Sunday) and cites at least two same-week "
        "reports from the flagged store. Confidence is the detector's surprise score, not a probability."
    )
    if flags.empty:
        st.info("No emerging issues flagged.")
        return
    shown = flags.merge(stores[["store_id", "store_name", "region"]], on="store_id", how="left")
    shown["evidence_count"] = shown["evidence_feedback_ids"].str.count(";") + 1
    st.dataframe(
        shown[["as_of_week_start", "region", "store_name", "issue_type_id", "confidence", "evidence_count"]],
        hide_index=True,
        width="stretch",
    )
    choice = st.selectbox(
        "Inspect flag",
        shown.index,
        format_func=lambda i: (
            f"{shown.loc[i, 'as_of_week_start']} · {shown.loc[i, 'store_name']} · {shown.loc[i, 'issue_type_id']}"
        ),
    )
    ids = shown.loc[choice, "evidence_feedback_ids"].split(";")
    evidence = records[records["feedback_id"].isin(ids)]
    st.dataframe(evidence[["created_at", "channel", "severity", "text"]], hide_index=True, width="stretch")


def show_queue(records: pd.DataFrame, week: pd.Timestamp) -> None:
    owners = sorted(records.loc[records["actionable"] == 1, "owner_function"].unique())
    owner = st.selectbox("Owner function", owners)
    queue = records[(records["week_start"] == week) & (records["owner_function"] == owner)].copy()
    queue["severity"] = pd.Categorical(queue["severity"], SEVERITY_ORDER, ordered=True)
    queue = queue.sort_values(["severity", "created_at"])
    st.caption(f"{len(queue)} routed records, {queue['incident_id'].nunique()} unique incidents after de-duplication.")
    st.dataframe(
        queue[["created_at", "store", "issue_type_id", "severity", "escalation", "sla_hours", "channel", "text"]],
        hide_index=True,
        width="stretch",
    )


def show_explorer(records: pd.DataFrame, taxonomy: pd.DataFrame) -> None:
    query = st.text_input("Search text", max_chars=100)
    types = st.multiselect("Issue types", taxonomy["issue_type_id"].tolist())
    channels = st.multiselect("Channels", sorted(records["channel"].unique()))
    shown = records
    if query:
        shown = shown[shown["text"].str.contains(query, case=False, regex=False)]
    if types:
        shown = shown[shown["issue_type_id"].isin(types)]
    if channels:
        shown = shown[shown["channel"].isin(channels)]
    st.caption(f"{len(shown):,} records (showing up to 500)")
    st.dataframe(
        shown[
            [
                "created_at",
                "channel",
                "store",
                "language",
                "issue_type_id",
                "issue_confidence",
                "severity",
                "actionable",
                "text",
            ]
        ].head(500),
        hide_index=True,
        width="stretch",
    )


def main() -> None:
    st.set_page_config(page_title="Voice-of-Store Engine", layout="wide")
    st.title("Voice-of-Store Engine")
    st.caption("Saffron Retail Group · synthetic hackathon data · R5")
    try:
        records, flags, taxonomy, stores = load_tables()
    except (FileNotFoundError, DataValidationError) as error:
        st.error(f"Outputs not found or invalid ({error}). Run `python FULL_CODE/main.py` first.")
        return
    week = week_picker(records)
    tabs = st.tabs(["Overview", "Regional brief", "Emerging issues", "Owner queues", "Explorer"])
    with tabs[0]:
        show_overview(records, flags, week)
    with tabs[1]:
        show_brief(records, flags, taxonomy, stores, week)
    with tabs[2]:
        show_flags(records, flags, stores)
    with tabs[3]:
        show_queue(records, week)
    with tabs[4]:
        show_explorer(records, taxonomy)


main()
