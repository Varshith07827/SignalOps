"""Clean a raw copy of the problem pack so ``data_io.load_pack`` accepts it.

``data_io`` validates strictly and stops at the first bad value. This module sits in front of it: it repairs
what can be repaired safely (stray whitespace, inconsistent casing, alias channel names, mixed date formats,
"IT1" for "IT01", duplicate rows), drops rows that cannot be repaired, and counts every change in a report.

It never rewrites the *meaning* of the feedback: text keeps its typos, emojis and mixed languages because the
classifier learns from them, and feedback ids keep their exact spelling because the evaluator matches on them.
"""

from __future__ import annotations

import html
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from voice_of_store.data_io import (
    CHANNELS,
    ISSUE_TYPES,
    MAX_TEXT_CHARS,
    REQUIRED_COLUMNS,
    SEVERITIES,
)

logger = logging.getLogger(__name__)

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"
LOCAL_TIMEZONE = "Asia/Kolkata"

# Values people type when a field is empty.
PLACEHOLDERS = frozenset({"", "na", "n/a", "nan", "none", "null", "nil", "-", "--", "?"})

CHANNEL_ALIASES = {
    "review": "online_review",
    "online": "online_review",
    "google_review": "online_review",
    "app": "in_app",
    "inapp": "in_app",
    "app_comment": "in_app",
    "staff_note": "staff_shift_note",
    "shift_note": "staff_shift_note",
    "call_centre": "call_centre_ticket",
    "call_center": "call_centre_ticket",
    "call_center_ticket": "call_centre_ticket",
    "call_centre_transcript": "call_centre_ticket",
}
SEVERITY_ALIASES = {
    "lo": "low",
    "med": "medium",
    "mid": "medium",
    "moderate": "medium",
    "hi": "high",
    "crit": "critical",
}
TRUE_VALUES = frozenset({"1", "1.0", "true", "yes", "y", "t"})
FALSE_VALUES = frozenset({"0", "0.0", "false", "no", "n", "f"})

# Invisible characters that break matching; the zero-width joiner stays because emoji sequences use it.
_INVISIBLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​⁠﻿]")
_WHITESPACE = re.compile(r"\s+")
_ISSUE_ID = re.compile(r"^(IT|NI)[\s_-]*0*(\d{1,2})$")
_ISO_DATE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_ISSUE_IDS = frozenset(ISSUE_TYPES)


@dataclass
class FileReport:
    """What cleaning did to one file: row counts, repairs and drops by reason."""

    rows_in: int = 0
    rows_out: int = 0
    fixed: Counter = field(default_factory=Counter)
    dropped: Counter = field(default_factory=Counter)

    def fix(self, reason: str, count: int) -> None:
        if count:
            self.fixed[reason] += int(count)

    def drop(self, reason: str, count: int) -> None:
        if count:
            self.dropped[reason] += int(count)

    def as_dict(self) -> dict:
        return {
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "fixed": dict(self.fixed),
            "dropped": dict(self.dropped),
        }


# ---------------------------------------------------------------------------------------------------------------
# Value-level helpers
# ---------------------------------------------------------------------------------------------------------------


def clean_text(value: str) -> str:
    """Unescape HTML entities, normalise Unicode (NFC), remove invisible characters and squeeze whitespace."""
    text = unicodedata.normalize("NFC", html.unescape(str(value)))
    text = _WHITESPACE.sub(" ", _INVISIBLE.sub("", text)).strip()
    return text[:MAX_TEXT_CHARS]


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in PLACEHOLDERS


def canonical_channel(value: str) -> str:
    key = re.sub(r"[\s\-]+", "_", value.strip().lower())
    return CHANNEL_ALIASES.get(key, key)


def canonical_issue_id(value: str) -> str:
    """'it1', 'IT-01' and 'IT 1' become 'IT01'. Anything else is returned upper-cased and unchanged."""
    upper = value.strip().upper()
    match = _ISSUE_ID.match(upper)
    return f"{match.group(1)}{int(match.group(2)):02d}" if match else upper


def canonical_store_id(value: str) -> str:
    """Upper-case, drop inner spaces and use a hyphen: ' st _ abcde ' becomes 'ST-ABCDE'."""
    if _is_placeholder(value):
        return ""
    return re.sub(r"\s+", "", value).upper().replace("_", "-")


def parse_timestamp(value: str) -> pd.Timestamp:
    """ISO dates as written; anything else day-first (Indian style). Time zones are converted to IST."""
    value = value.strip()
    if _is_placeholder(value):
        return pd.NaT
    try:
        stamp = pd.Timestamp(value) if _ISO_DATE.match(value) else pd.to_datetime(value, dayfirst=True)
    except (ValueError, TypeError, OverflowError):
        return pd.NaT
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(LOCAL_TIMEZONE).tz_localize(None)
    return stamp


def parse_rating(value: str) -> str:
    """'4', '4.0', '4/5' and '4 stars' become '4'. Blank, out of 1-5 or unreadable become ''."""
    if _is_placeholder(value):
        return ""
    stars = value.count("★")
    if stars and not value.replace("★", "").replace("☆", "").strip():
        return str(stars) if 1 <= stars <= 5 else ""
    match = _NUMBER.search(value)
    if not match:
        return ""
    number = float(match.group())
    return f"{number:g}" if 1 <= number <= 5 else ""


def _unify_case(values: pd.Series) -> pd.Series:
    """Spell every case-variant of a value ('west', 'WEST', 'West') the way it is spelled most often."""
    spellings = values[values != ""].value_counts()
    preferred: dict[str, str] = {}
    for spelling in spellings.index:  # most common first
        preferred.setdefault(spelling.lower(), spelling)
    return values.map(lambda v: preferred.get(v.lower(), v))


# ---------------------------------------------------------------------------------------------------------------
# File-level cleaning
# ---------------------------------------------------------------------------------------------------------------


def read_raw(path: Path, report: FileReport) -> pd.DataFrame:
    """Read every cell as text, strip a byte-order mark, and fall back to Windows-1252 if the file isn't UTF-8."""
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except UnicodeDecodeError:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="cp1252")
        report.fix("re-encoded from Windows-1252 to UTF-8", len(frame))
    renamed = {c: c.strip().lower().replace(" ", "_") for c in frame.columns}
    report.fix("column names tidied", sum(old != new for old, new in renamed.items()))
    frame = frame.rename(columns=renamed)
    report.rows_in = len(frame)
    return frame


def _common_cleanup(frame: pd.DataFrame, report: FileReport) -> pd.DataFrame:
    """Strip every cell, then drop blank rows and exact duplicate rows."""
    stripped = frame.apply(lambda col: col.str.strip())
    report.fix("cells with stray whitespace", int((stripped != frame).to_numpy().sum()))
    blank = (stripped == "").all(axis=1)
    report.drop("blank row", blank.sum())
    stripped = stripped[~blank]
    duplicate = stripped.duplicated()
    report.drop("exact duplicate row", duplicate.sum())
    return stripped[~duplicate]


def _drop(frame: pd.DataFrame, mask: pd.Series, reason: str, report: FileReport) -> pd.DataFrame:
    report.drop(reason, mask.sum())
    return frame[~mask]


def _apply(frame: pd.DataFrame, column: str, func, reason: str, report: FileReport) -> None:
    cleaned = frame[column].map(func)
    report.fix(reason, (cleaned != frame[column]).sum())
    frame[column] = cleaned


def _require_columns(frame: pd.DataFrame, name: str) -> None:
    missing = [c for c in REQUIRED_COLUMNS[name] if c not in frame.columns]
    if missing:
        raise ValueError(f"{name} is missing columns {missing}; it cannot be cleaned")


def clean_feedback(frame: pd.DataFrame, report: FileReport, known_stores: set[str] | None = None) -> pd.DataFrame:
    _require_columns(frame, "feedback.csv")
    frame = _common_cleanup(frame, report).copy()

    frame = _drop(frame, frame["feedback_id"] == "", "missing feedback_id", report)
    conflict = frame["feedback_id"].duplicated()
    frame = _drop(frame, conflict, "feedback_id repeated with different content (kept the first)", report)

    _apply(frame, "channel", canonical_channel, "channel spelling normalised", report)
    frame = _drop(frame, ~frame["channel"].isin(CHANNELS), "unknown channel", report)

    stamps = frame["created_at"].map(parse_timestamp)
    frame = _drop(frame, stamps.isna(), "unreadable created_at", report)
    stamps = stamps[stamps.notna()]
    formatted = stamps.map(lambda s: s.strftime(TIMESTAMP_FORMAT))
    report.fix("created_at rewritten as ISO", (formatted != frame["created_at"]).sum())
    frame["created_at"] = formatted

    _apply(frame, "store_id", canonical_store_id, "store_id normalised", report)
    if known_stores is not None:
        unknown = (frame["store_id"] != "") & ~frame["store_id"].isin(known_stores)
        report.fix("unknown store_id blanked (store is then found from the text)", unknown.sum())
        frame.loc[unknown, "store_id"] = ""

    _apply(frame, "rating", parse_rating, "rating normalised or blanked", report)
    _apply(frame, "text", clean_text, "text tidied", report)
    report.fix("empty text kept (no content to classify)", (frame["text"] == "").sum())

    report.rows_out = len(frame)
    return frame.reset_index(drop=True)


def _parse_flag(value: str) -> str:
    lowered = value.lower()
    if lowered in TRUE_VALUES:
        return "1"
    return "0" if lowered in FALSE_VALUES else value


def clean_labels(frame: pd.DataFrame, report: FileReport, feedback_ids: set[str] | None = None) -> pd.DataFrame:
    _require_columns(frame, "feedback_labels_train.csv")
    frame = _common_cleanup(frame, report).copy()
    _apply(frame, "issue_type_id", canonical_issue_id, "issue_type_id normalised", report)
    _apply(frame, "severity", lambda v: SEVERITY_ALIASES.get(v.lower(), v.lower()), "severity normalised", report)
    _apply(frame, "actionable", _parse_flag, "actionable written as 0/1", report)

    frame = _drop(frame, ~frame["issue_type_id"].isin(_ISSUE_IDS), "unknown issue_type_id", report)
    frame = _drop(frame, ~frame["severity"].isin(SEVERITIES), "unknown severity", report)
    frame = _drop(frame, ~frame["actionable"].isin({"0", "1"}), "actionable not 0/1", report)
    if feedback_ids is not None:
        orphan = ~frame["feedback_id"].isin(feedback_ids)
        frame = _drop(frame, orphan, "label for a feedback_id not in feedback", report)
    frame = _drop(frame, frame["feedback_id"].duplicated(), "feedback labelled twice (kept the first)", report)
    report.rows_out = len(frame)
    return frame.reset_index(drop=True)


def clean_stores(frame: pd.DataFrame, report: FileReport) -> pd.DataFrame:
    _require_columns(frame, "store_master.csv")
    frame = _common_cleanup(frame, report).copy()
    _apply(frame, "store_id", canonical_store_id, "store_id normalised", report)
    frame = _drop(frame, frame["store_id"] == "", "missing store_id", report)
    frame = _drop(frame, frame["store_id"].duplicated(), "store_id repeated (kept the first)", report)
    for column in ("store_name", "city", "region", "format"):
        _apply(frame, column, lambda v: _WHITESPACE.sub(" ", v), f"{column} whitespace squeezed", report)
    for column in ("city", "region", "format"):
        unified = _unify_case(frame[column])
        report.fix(f"{column} casing unified", (unified != frame[column]).sum())
        frame[column] = unified
    footfall = pd.to_numeric(frame["avg_weekly_footfall"].str.replace(",", ""), errors="coerce")
    cleaned = footfall.map(lambda n: f"{n:g}" if pd.notna(n) and n >= 0 else "")
    report.fix("avg_weekly_footfall normalised or blanked", (cleaned != frame["avg_weekly_footfall"]).sum())
    frame["avg_weekly_footfall"] = cleaned
    report.rows_out = len(frame)
    return frame.reset_index(drop=True)


def clean_taxonomy(frame: pd.DataFrame, report: FileReport) -> pd.DataFrame:
    _require_columns(frame, "issue_taxonomy.csv")
    frame = _common_cleanup(frame, report).copy()
    _apply(frame, "issue_type_id", canonical_issue_id, "issue_type_id normalised", report)
    floor = "policy_severity_floor"
    _apply(frame, floor, lambda v: SEVERITY_ALIASES.get(v.lower(), v.lower()), "severity floor normalised", report)
    frame = _drop(frame, ~frame["issue_type_id"].isin(_ISSUE_IDS), "unknown issue_type_id", report)
    frame = _drop(frame, frame["issue_type_id"].duplicated(), "issue_type_id repeated (kept the first)", report)
    report.rows_out = len(frame)
    return frame.reset_index(drop=True)


def clean_calendar(frame: pd.DataFrame, report: FileReport) -> pd.DataFrame:
    _require_columns(frame, "week_calendar.csv")
    frame = _common_cleanup(frame, report).copy()
    for column in ("week_start", "week_end"):
        days = frame[column].map(parse_timestamp)
        frame = _drop(frame, days.isna(), f"unreadable {column}", report)
        formatted = days[days.notna()].map(lambda d: d.strftime("%Y-%m-%d"))
        report.fix(f"{column} rewritten as YYYY-MM-DD", (formatted != frame[column]).sum())
        frame[column] = formatted
    frame = _drop(frame, frame["week_start"].duplicated(), "week repeated (kept the first)", report)
    frame = frame.sort_values("week_start")
    renumbered = [str(i) for i in range(1, len(frame) + 1)]
    report.fix("week_index renumbered in date order", (frame["week_index"] != renumbered).sum())
    frame["week_index"] = renumbered
    report.rows_out = len(frame)
    return frame.reset_index(drop=True)


# ---------------------------------------------------------------------------------------------------------------
# Whole pack
# ---------------------------------------------------------------------------------------------------------------


def clean_pack(source: Path, destination: Path) -> dict[str, dict]:
    """Clean every pack file found in ``source`` and write it, same name and columns, into ``destination``.

    Stores and taxonomy are cleaned first so feedback can be checked against the known store ids, and labels
    against the cleaned feedback ids. Returns the per-file report; missing optional files are listed as such.
    """
    source, destination = Path(source), Path(destination)
    if not (source / "feedback.csv").is_file():
        raise FileNotFoundError(f"No feedback.csv in {source}")
    destination.mkdir(parents=True, exist_ok=True)
    reports: dict[str, dict] = {}
    cleaned: dict[str, pd.DataFrame] = {}

    def run(name: str, cleaner, **kwargs) -> None:
        path = source / name
        if not path.is_file():
            reports[name] = {"missing": True}
            logger.warning("%s not found in %s; skipped", name, source)
            return
        report = FileReport()
        frame = cleaner(read_raw(path, report), report, **kwargs)
        frame.to_csv(destination / name, index=False)
        cleaned[name] = frame
        reports[name] = report.as_dict()
        dropped = sum(report.dropped.values())
        logger.info("%s: %d rows in, %d out, %d dropped", name, report.rows_in, report.rows_out, dropped)

    run("store_master.csv", clean_stores)
    run("issue_taxonomy.csv", clean_taxonomy)
    run("week_calendar.csv", clean_calendar)
    stores = cleaned.get("store_master.csv")
    run("feedback.csv", clean_feedback, known_stores=None if stores is None else set(stores["store_id"]))
    run("feedback_labels_train.csv", clean_labels, feedback_ids=set(cleaned["feedback.csv"]["feedback_id"]))
    return reports
