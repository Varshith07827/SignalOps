"""Cross-channel de-duplication (stretch goal): the same real-world incident reported several times counts once.

Two reports join one incident when they concern the same store and the same predicted issue type and were
created within ``window_hours`` of the incident's first report. This is deliberately conservative: reports
without a known store are never merged, because "milk finished again" at two unknown stores are two incidents.
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
