"""Orchestration shared by the CLI entry points and the dashboard."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from voice_of_store.brief import attach_regions
from voice_of_store.classifier import FeedbackClassifier, build_training_frame
from voice_of_store.config import Settings
from voice_of_store.data_io import PackData, load_pack
from voice_of_store.dedup import assign_incidents
from voice_of_store.detector import FLAG_COLUMNS, detect_flags
from voice_of_store.routing import route_records
from voice_of_store.text import detect_language, resolve_stores

logger = logging.getLogger(__name__)

MIN_CLASSES_TO_TRAIN = 2


class InsufficientLabelsError(RuntimeError):
    """Too few labelled records are visible (e.g. an as-of week before any labels) to train a classifier."""


@dataclass(frozen=True)
class EngineRun:
    data: PackData
    records: pd.DataFrame
    weeks: list[pd.Timestamp]


def monday_of(day: pd.Timestamp) -> pd.Timestamp:
    return (day - pd.Timedelta(days=day.weekday())).normalize()


def with_stores(data: PackData) -> pd.DataFrame:
    """Feedback rows plus the resolved ``store`` each one is about (None when unknown)."""
    feedback = data.feedback.copy()
    feedback["store"] = resolve_stores(feedback, data.stores)
    return feedback


def train_model(data: PackData, feedback: pd.DataFrame, settings: Settings) -> FeedbackClassifier:
    """Fit on the labelled records present in ``feedback``.

    Labels whose feedback row is absent (created after an as-of cutoff) are not used, so a causal run never
    learns from future text.
    """
    train = build_training_frame(feedback, data.labels, feedback["store"].notna())
    targets = (train.issue_type_id, train.severity, train.actionable)
    if min(target.nunique() for target in targets) < MIN_CLASSES_TO_TRAIN:
        raise InsufficientLabelsError(f"only {len(train.feedback)} labelled records visible; cannot train")
    return FeedbackClassifier(settings.classifier, data.taxonomy).fit(train)


def classify_feedback(data: PackData, settings: Settings) -> pd.DataFrame:
    """Train on the visible labelled sample and label every feedback row in ``data``."""
    feedback = with_stores(data)
    model = train_model(data, feedback, settings)
    return feedback.join(model.predict(feedback, feedback["store"].notna()))


def enrich_records(records: pd.DataFrame, data: PackData, settings: Settings) -> pd.DataFrame:
    """Add language, owner routing, cross-channel incident ids and region for the briefs and dashboard."""
    enriched = route_records(records, data.taxonomy, settings.routing)
    enriched["language"] = enriched["text"].map(detect_language)
    enriched["incident_id"] = assign_incidents(enriched, settings.dedup.window_hours)
    enriched["region"] = attach_regions(enriched, data.stores)
    return enriched


def week_range(data: PackData) -> list[pd.Timestamp]:
    """Every Monday from the first to the last week seen in the calendar or the feedback."""
    mondays = pd.concat([data.calendar["week_start"], data.feedback["week_start"]])
    return list(pd.date_range(mondays.min(), mondays.max(), freq="7D"))


def run_engine(data_dir: Path, settings: Settings) -> EngineRun:
    """Load the whole pack and produce fully enriched record-level predictions."""
    data = load_pack(data_dir)
    records = enrich_records(classify_feedback(data, settings), data, settings)
    return EngineRun(data=data, records=records, weeks=week_range(data))


def flags_as_of(data: PackData, records: pd.DataFrame, monday: pd.Timestamp, settings: Settings) -> pd.DataFrame:
    """Flags for the week starting ``monday``, using only records created before the following Monday."""
    visible = records[records["created_at"] < monday + pd.Timedelta(days=7)]
    stores = sorted(data.stores["store_id"])
    return detect_flags(visible, stores, data.taxonomy, week_range(data), {monday}, settings.detector)


def detect_week(data_dir: Path, as_of: pd.Timestamp, settings: Settings) -> pd.DataFrame:
    """What ``detect.py`` runs: drop future feedback first, then train, classify and detect."""
    monday = monday_of(as_of)
    data = load_pack(data_dir, cutoff=monday + pd.Timedelta(days=7))
    try:
        records = classify_feedback(data, settings)
    except InsufficientLabelsError as error:
        logger.warning("No flags for week %s: %s", monday.date(), error)
        return pd.DataFrame(columns=FLAG_COLUMNS)
    return flags_as_of(data, records, monday, settings)


def replay_weekly_flags(data: PackData, settings: Settings) -> pd.DataFrame:
    """Reproduce ``detect_week`` for every week without reloading files.

    Classification is per row and training is deterministic, so a model trained on the labels visible at week w
    gives the same labels whether it predicts the truncated or the full stream. The model is retrained only when
    the visible label set changes; ``flags_as_of`` then hides every row created after week w.
    """
    feedback = with_stores(data)
    weekly = []
    records = None
    trained_on: frozenset[str] | None = None
    for monday in week_range(data):
        visible = feedback[feedback["created_at"] < monday + pd.Timedelta(days=7)]
        labels_seen = frozenset(data.labels["feedback_id"][data.labels["feedback_id"].isin(visible["feedback_id"])])
        if labels_seen != trained_on:
            trained_on = labels_seen
            try:
                model = train_model(data, visible, settings)
            except InsufficientLabelsError as error:
                logger.warning("No flags for week %s: %s", monday.date(), error)
                records = None
                continue
            records = feedback.join(model.predict(feedback, feedback["store"].notna()))
        if records is not None:
            weekly.append(flags_as_of(data, records, monday, settings))
    weekly = [frame for frame in weekly if not frame.empty]
    flags = pd.concat(weekly, ignore_index=True) if weekly else pd.DataFrame(columns=FLAG_COLUMNS)
    logger.info("Replayed %d weeks: %d flags", len(weekly), len(flags))
    return flags
