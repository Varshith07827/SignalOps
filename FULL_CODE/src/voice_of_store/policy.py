"""Annotation-guideline rules that sit on top of the learned models.

These encode the labelling policy rather than anything learnt: severity is never below the taxonomy's policy
floor, and a record can only be actionable when it is a real issue that can be routed to an owner.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from voice_of_store.data_io import NON_ISSUE_TYPES, SEVERITIES

SEVERITY_RANK = {name: rank for rank, name in enumerate(SEVERITIES)}
# Order, app, payment, refund and loyalty issues are routed to Digital / Supply Chain without a store.
STORELESS_ROUTABLE_TYPES = frozenset(f"IT{i}" for i in range(23, 30))


def apply_severity_floor(predicted: pd.Series, issue_types: pd.Series, taxonomy: pd.DataFrame) -> pd.Series:
    """Severity = max(policy floor of the issue type, predicted impact)."""
    floors = issue_types.map(taxonomy["policy_severity_floor"]).fillna("low")
    predicted_rank = predicted.map(SEVERITY_RANK).to_numpy()
    floor_rank = floors.map(SEVERITY_RANK).to_numpy()
    return pd.Series(np.array(SEVERITIES)[np.maximum(predicted_rank, floor_rank)], index=predicted.index)


def can_be_actionable(issue_types: pd.Series, store_known: pd.Series) -> pd.Series:
    """True when the guideline allows actionable = 1: a real issue whose owner can be reached."""
    is_issue = ~issue_types.isin(NON_ISSUE_TYPES)
    routable = store_known | issue_types.isin(STORELESS_ROUTABLE_TYPES)
    return is_issue & routable
