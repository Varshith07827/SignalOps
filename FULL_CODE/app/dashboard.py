"""Streamlit dashboard: plain-English insights, briefs, early warnings, owner queues, explorer and a Run tab.

    streamlit run FULL_CODE/app/dashboard.py

Presentation only: all logic lives in ``voice_of_store``. The analysis tabs read the tables ``main.py`` writes;
the Run tab can rebuild them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from views.analysis import (  # noqa: E402
    in_weeks,
    show_brief,
    show_explorer,
    show_flags,
    show_overview,
    show_queue,
)
from views.insights import show_insights  # noqa: E402
from views.runner import show_runner  # noqa: E402
from voice_of_store.config import load_settings  # noqa: E402
from voice_of_store.data_io import DataValidationError, load_pack  # noqa: E402

SETTINGS = load_settings()
TABS = ["Insights", "Overview", "Regional brief", "Early warnings", "Owner queues", "Explorer", "Run"]


@st.cache_data(show_spinner="Loading data...")
def load_reference() -> tuple[pd.DataFrame, pd.DataFrame, list[pd.Timestamp]]:
    pack = load_pack(SETTINGS.paths.data_dir)
    weeks = sorted(pd.Timestamp(w) for w in pack.calendar["week_start"])
    return pack.taxonomy.reset_index(), pack.stores, weeks


@st.cache_data(show_spinner="Loading engine outputs...")
def load_outputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    outputs = SETTINGS.paths.outputs_dir
    records = pd.read_csv(outputs / "records.csv", parse_dates=["created_at", "week_start"])
    return records, pd.read_csv(outputs / "flags.csv")


def week_range(weeks: list[pd.Timestamp]) -> tuple[pd.Timestamp, pd.Timestamp]:
    st.sidebar.header("Weeks")
    first, last = st.sidebar.select_slider(
        "Show weeks",
        options=weeks,
        value=(weeks[max(0, len(weeks) - 4)], weeks[-1]),
        format_func=lambda w: f"{w:%d %b}",
    )
    st.sidebar.caption(f"{first:%d %b %Y} to {last + pd.Timedelta(days=6):%d %b %Y}")
    return first, last


def main() -> None:
    st.set_page_config(page_title="Voice-of-Store Engine", layout="wide")
    st.title("Voice-of-Store Engine")
    st.caption("Saffron Retail Group · R5 · synthetic hackathon data")
    try:
        taxonomy, stores, weeks = load_reference()
    except DataValidationError as error:
        st.error(f"Problem with the data in {SETTINGS.paths.data_dir}: {error}")
        return
    first, last = week_range(weeks)
    tabs = dict(zip(TABS, st.tabs(TABS), strict=True))
    with tabs["Run"]:
        show_runner(SETTINGS, weeks)
    try:
        records, flags = load_outputs()
    except FileNotFoundError:
        st.warning("No engine outputs yet: open the Run tab and click Rebuild.")
        return
    chosen_records = in_weeks(records, "week_start", first, last)
    chosen_flags = in_weeks(flags, "as_of_week_start", first, last)
    with tabs["Insights"]:
        show_insights(records, flags, SETTINGS.paths.outputs_dir)
    with tabs["Overview"]:
        show_overview(records, flags, first, last)
    with tabs["Regional brief"]:
        show_brief(records, flags, taxonomy, stores, last, SETTINGS.brief)
    with tabs["Early warnings"]:
        show_flags(records, chosen_flags, stores)
    with tabs["Owner queues"]:
        show_queue(records, last)
    with tabs["Explorer"]:
        show_explorer(chosen_records, taxonomy)


main()
