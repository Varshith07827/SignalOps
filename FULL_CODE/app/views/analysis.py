"""Tabs that read the engine's outputs: overview, regional brief, emerging issues, owner queues, explorer."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from voice_of_store.brief import build_region_brief, render_markdown
from voice_of_store.config import BriefSettings

SEVERITY_ORDER = ["critical", "high", "medium", "low"]


def in_weeks(frame: pd.DataFrame, column: str, first: pd.Timestamp, last: pd.Timestamp) -> pd.DataFrame:
    weeks = pd.to_datetime(frame[column])
    return frame[(weeks >= first) & (weeks <= last)]


def show_overview(records: pd.DataFrame, flags: pd.DataFrame, first: pd.Timestamp, last: pd.Timestamp) -> None:
    chosen = in_weeks(records, "week_start", first, last)
    actionable = chosen[chosen["actionable"] == 1]
    cols = st.columns(4)
    cols[0].metric("Feedback in range", f"{len(chosen):,}")
    cols[1].metric("Needs action", f"{len(actionable):,}")
    cols[2].metric("High / critical", f"{int(actionable['severity'].isin(['high', 'critical']).sum()):,}")
    cols[3].metric("Early-warning flags", len(in_weeks(flags, "as_of_week_start", first, last)))
    left, right = st.columns(2)
    left.subheader("Who has to act")
    left.bar_chart(actionable["owner_function"].value_counts())
    right.subheader("Languages in the feedback")
    right.bar_chart(chosen["language"].value_counts())
    st.subheader("Records needing action, per week and region")
    st.line_chart(actionable.groupby(["week_start", "region"]).size().unstack(fill_value=0))


def show_brief(
    records: pd.DataFrame,
    flags: pd.DataFrame,
    taxonomy: pd.DataFrame,
    stores: pd.DataFrame,
    week: pd.Timestamp,
    settings: BriefSettings,
) -> None:
    st.caption(f"The brief covers one week: the last week of your range ({week:%d %b %Y}).")
    region = st.selectbox("Region", sorted(records["region"].unique()))
    names = dict(zip(stores["store_id"], stores["store_name"], strict=True))
    items = build_region_brief(records, flags, region, week, taxonomy.set_index("issue_type_id"), names, settings)
    markdown = render_markdown(region, week, items)
    st.markdown(markdown)
    st.download_button("Download brief (Markdown)", markdown, file_name=f"brief_{region}_{week:%Y-%m-%d}.md")


def show_flags(records: pd.DataFrame, flags: pd.DataFrame, stores: pd.DataFrame) -> None:
    st.caption(
        "Each flag says: this store has an unusual rise in this issue this week. It uses only feedback up to that "
        "week's Sunday and cites at least two same-week reports. Confidence is a surprise score, not a probability."
    )
    if flags.empty:
        st.info("No early-warning flags in the selected weeks.")
        return
    shown = flags.merge(stores[["store_id", "store_name", "region"]], on="store_id", how="left").reset_index(drop=True)
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
    st.caption(f"Work queue for one week: {week:%d %b %Y}.")
    owners = sorted(records.loc[records["actionable"] == 1, "owner_function"].unique())
    owner = st.selectbox("Owner function", owners)
    queue = records[(records["week_start"] == week) & (records["owner_function"] == owner)].copy()
    queue["severity"] = pd.Categorical(queue["severity"], SEVERITY_ORDER, ordered=True)
    queue = queue.sort_values(["severity", "created_at"])
    st.caption(f"{len(queue)} records, {queue['incident_id'].nunique()} separate incidents after merging duplicates.")
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
    st.caption(f"{len(shown):,} records in the selected weeks (showing up to 500)")
    columns = [
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
    st.dataframe(shown[columns].head(500), hide_index=True, width="stretch")
