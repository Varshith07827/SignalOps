"""Load and validate the problem pack's CSV files from one data folder.

Every file is read from the folder that holds ``feedback.csv``; the jury re-run hands us a disguised copy of that
folder (fresh ids, shifted dates), so nothing here may depend on concrete ids or dates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

CHANNELS = frozenset({"online_review", "in_app", "staff_shift_note", "call_centre_ticket"})
SEVERITIES = ("low", "medium", "high", "critical")
ISSUE_TYPES = tuple(f"IT{i:02d}" for i in range(1, 31)) + ("NI01", "NI02", "NI03")
NON_ISSUE_TYPES = frozenset({"NI01", "NI02", "NI03"})
MAX_TEXT_CHARS = 5000

REQUIRED_COLUMNS = {
    "feedback.csv": ["feedback_id", "channel", "created_at", "store_id", "rating", "text"],
    "feedback_labels_train.csv": ["feedback_id", "issue_type_id", "severity", "actionable"],
    "store_master.csv": ["store_id", "store_name", "city", "region", "format", "avg_weekly_footfall"],
    "issue_taxonomy.csv": ["issue_type_id", "issue_type", "owner_function", "policy_severity_floor"],
    "week_calendar.csv": ["week_index", "week_start", "week_end"],
}


class DataValidationError(ValueError):
    """Raised when an input file is missing, malformed or holds out-of-range values."""


@dataclass(frozen=True)
class PackData:
    feedback: pd.DataFrame
    labels: pd.DataFrame
    stores: pd.DataFrame
    taxonomy: pd.DataFrame
    calendar: pd.DataFrame


def week_start_of(timestamps: pd.Series) -> pd.Series:
    """Monday 00:00 of the Monday-Sunday week each timestamp falls in."""
    days = timestamps.dt.normalize()
    return days - pd.to_timedelta(days.dt.weekday, unit="D")


def _read_csv(folder: Path, name: str) -> pd.DataFrame:
    path = folder / name
    if not path.is_file():
        raise DataValidationError(f"Missing input file: {path}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in REQUIRED_COLUMNS[name] if c not in frame.columns]
    if missing:
        raise DataValidationError(f"{name} is missing columns {missing}")
    return frame


def validate_feedback(raw: pd.DataFrame) -> pd.DataFrame:
    """Type-check the feedback stream and add ``week_start``. Rejects unknown channels and duplicate ids."""
    frame = raw.copy()
    if frame["feedback_id"].duplicated().any():
        raise DataValidationError("feedback.csv has duplicate feedback_id values")
    unknown = set(frame["channel"]) - CHANNELS
    if unknown:
        raise DataValidationError(f"feedback.csv has unknown channels: {sorted(unknown)}")
    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce")
    if frame["created_at"].isna().any():
        raise DataValidationError("feedback.csv has unparseable created_at values")
    frame["rating"] = pd.to_numeric(frame["rating"].replace("", None), errors="coerce")
    if ((frame["rating"] < 1) | (frame["rating"] > 5)).any():
        raise DataValidationError("feedback.csv has ratings outside 1-5")
    frame["store_id"] = frame["store_id"].str.strip().str.upper().replace("", None)
    frame["text"] = frame["text"].fillna("").str.slice(0, MAX_TEXT_CHARS)
    frame["week_start"] = week_start_of(frame["created_at"])
    return frame.reset_index(drop=True)


def validate_labels(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    bad_type = ~frame["issue_type_id"].isin(ISSUE_TYPES)
    bad_sev = ~frame["severity"].isin(SEVERITIES)
    bad_act = ~frame["actionable"].isin({"0", "1"})
    if (bad_type | bad_sev | bad_act).any():
        raise DataValidationError("feedback_labels_train.csv has out-of-range label values")
    frame["actionable"] = frame["actionable"].astype(int)
    return frame


def validate_stores(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    frame["store_id"] = frame["store_id"].str.strip().str.upper()
    frame["avg_weekly_footfall"] = pd.to_numeric(frame["avg_weekly_footfall"], errors="coerce")
    # Locality = the store name after "Saffron <Format> ", the rule evaluate.py uses for store attribution.
    parts = frame["store_name"].str.split(" ", n=2)
    if (parts.str.len() < 3).any():
        raise DataValidationError("store_master.csv has store names without a locality")
    frame["locality"] = parts.str[2].str.lower().str.strip()
    return frame


def load_pack(folder: Path, cutoff: pd.Timestamp | None = None) -> PackData:
    """Load all five files from ``folder``. With ``cutoff``, drop feedback created at or after it."""
    folder = Path(folder)
    feedback = validate_feedback(_read_csv(folder, "feedback.csv"))
    if cutoff is not None:
        feedback = feedback[feedback["created_at"] < cutoff].reset_index(drop=True)
    calendar = _read_csv(folder, "week_calendar.csv")
    calendar["week_start"] = pd.to_datetime(calendar["week_start"])
    data = PackData(
        feedback=feedback,
        labels=validate_labels(_read_csv(folder, "feedback_labels_train.csv")),
        stores=validate_stores(_read_csv(folder, "store_master.csv")),
        taxonomy=_read_csv(folder, "issue_taxonomy.csv").set_index("issue_type_id"),
        calendar=calendar,
    )
    logger.info("Loaded %d feedback rows and %d labels from %s", len(feedback), len(data.labels), folder)
    return data
