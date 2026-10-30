"""Merge reports of the same incident that came in through different channels.

Reports are merged when they have the same store and issue type and arrive within window_hours of the
first report. Reports without a known store are never merged.
"""

from __future__ import annotations

import pandas as pd


def assign_incidents(labelled: pd.DataFrame, window_hours: float) -> pd.Series:
    """Return an incident id per record (records without a store get their own feedback_id)."""
    incident = labelled["feedback_id"].copy()
    has_store = labelled["store"].notna() & (labelled["actionable"] == 1)
    rows = labelled[has_store].sort_values("created_at")
    window = pd.Timedelta(hours=window_hours)
    for _, group in rows.groupby(["store", "issue_type_id"], sort=False):
        anchor_time = None
        anchor_id = None
        for idx, created, fid in zip(group.index, group["created_at"], group["feedback_id"], strict=True):
            if anchor_time is None or created - anchor_time > window:
                anchor_time, anchor_id = created, fid
            incident[idx] = anchor_id
    return incident
