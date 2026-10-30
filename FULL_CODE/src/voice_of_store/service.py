"""Engine behind the web dashboard: trains once on the R5 dataset, then analyses it or an uploaded file."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, replace

import pandas as pd

from voice_of_store.config import Settings
from voice_of_store.data_io import REQUIRED_COLUMNS, DataValidationError, load_pack, validate_feedback
from voice_of_store.detector import detect_flags
from voice_of_store.evaluation import cross_validate
from voice_of_store.pipeline import enrich_records, train_model, week_range, with_stores

logger = logging.getLogger(__name__)

DATASET_NAME = "R5 dataset"


class UploadError(ValueError):
    """Raised for an uploaded file we can't use. The message is shown to the user."""


@dataclass(frozen=True)
class Analysis:
    name: str
    records: pd.DataFrame
    flags: pd.DataFrame
    weeks: list[pd.Timestamp]
    regions: list[str]


def parse_feedback_upload(filename: str, content: bytes, max_bytes: int) -> pd.DataFrame:
    """Check an uploaded CSV and return it as validated feedback rows."""
    if not filename.lower().endswith(".csv"):
        raise UploadError("Please upload a .csv file.")
    if not content:
        raise UploadError("The file is empty.")
    if len(content) > max_bytes:
        raise UploadError(f"The file is larger than {max_bytes // (1024 * 1024)} MB.")
    try:
        raw = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as error:
        raise UploadError("This file could not be read as a CSV.") from error
    missing = [c for c in REQUIRED_COLUMNS["feedback.csv"] if c not in raw.columns]
    if missing:
        raise UploadError(f"The file is missing these columns: {', '.join(missing)}.")
    if raw.empty:
        raise UploadError("The file has no rows.")
    try:
        return validate_feedback(raw)
    except DataValidationError as error:
        raise UploadError(str(error)) from error


class Engine:
    """Loads the data folder and trains the classifier on its labelled records."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.reference = load_pack(settings.paths.data_dir)
        self.model = train_model(self.reference, with_stores(self.reference), settings)
        self._quality: dict[str, float] | None = None

    def analyse(self, feedback: pd.DataFrame, name: str) -> Analysis:
        """Label, route and de-duplicate every row, then run the weekly early-warning detector."""
        # Uploaded files may cover different weeks, so the calendar comes from the rows themselves.
        calendar = pd.DataFrame({"week_start": sorted(feedback["week_start"].unique())})
        data = replace(self.reference, feedback=feedback, calendar=calendar)
        rows = with_stores(data)
        records = enrich_records(rows.join(self.model.predict(rows, rows["store"].notna())), data, self.settings)
        weeks = week_range(data)
        stores = sorted(data.stores["store_id"])
        flags = detect_flags(records, stores, data.taxonomy, weeks, set(weeks), self.settings.detector)
        logger.info("Analysed %s: %d rows, %d weeks, %d warnings", name, len(records), len(weeks), len(flags))
        return Analysis(name, records, flags, weeks, sorted(records["region"].unique()))

    def analyse_dataset(self) -> Analysis:
        return self.analyse(self.reference.feedback, DATASET_NAME)

    def quality(self) -> dict[str, float]:
        """5-fold cross-validated scores. Takes about 15 seconds, so it's computed once."""
        if self._quality is None:
            self._quality = cross_validate(self.reference, self.settings)
        return self._quality
