"""Rules from the labelling guideline, applied after the models.

Severity is never below the taxonomy's policy floor, and only a real issue that can be routed
to an owner can be actionable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from voice_of_store.data_io import NON_ISSUE_TYPES, SEVERITIES

SEVERITY_RANK = {name: rank for rank, name in enumerate(SEVERITIES)}
# Online order, app, payment, refund and loyalty issues don't need a store to be routed.
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
