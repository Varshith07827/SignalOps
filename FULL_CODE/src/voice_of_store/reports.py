"""Write the submission files, the routed record table and the Markdown regional briefs."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from voice_of_store.brief import build_region_brief, render_markdown
from voice_of_store.config import Settings
from voice_of_store.pipeline import EngineRun

logger = logging.getLogger(__name__)

PREDICTION_COLUMNS = ["feedback_id", "issue_type_id", "severity", "actionable"]
DETECTOR_COMMAND = "python FULL_CODE/detect.py --feedback {feedback} --as-of {asof} --out {out}\n"
RECORD_COLUMNS = [
    "feedback_id",
    "channel",
    "created_at",
    "week_start",
    "store",
    "region",
    "language",
    "rating",
    "text",
    "issue_type_id",
    "issue_confidence",
    "severity",
    "actionable",
    "owner_function",
    "escalation",
    "sla_hours",
    "incident_id",
]


def write_submission(records: pd.DataFrame, flags: pd.DataFrame, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    records[PREDICTION_COLUMNS].to_csv(folder / "R5_predictions.csv", index=False)
    flags.to_csv(folder / "R5_emerging_flags.csv", index=False)
    (folder / "detector_cmd.txt").write_text(DETECTOR_COMMAND, encoding="utf-8")
    logger.info("Wrote %d predictions and %d flags to %s", len(records), len(flags), folder)


def write_records(records: pd.DataFrame, folder: Path) -> None:
    """Every record with its labels, routing, language and incident id (the routing deliverable)."""
    folder.mkdir(parents=True, exist_ok=True)
    records[RECORD_COLUMNS].to_csv(folder / "records.csv", index=False)


def write_briefs(run: EngineRun, flags: pd.DataFrame, settings: Settings) -> Path:
    """Write one Markdown brief per region for the latest week with data; returns the folder."""
    week = run.records["week_start"].max()
    folder = settings.paths.outputs_dir / "briefs" / f"{week:%Y-%m-%d}"
    folder.mkdir(parents=True, exist_ok=True)
    names = dict(zip(run.data.stores["store_id"], run.data.stores["store_name"], strict=True))
    for region in sorted(run.records["region"].unique()):
        items = build_region_brief(run.records, flags, region, week, run.data.taxonomy, names, settings.brief)
        slug = region.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("&", "and")
        (folder / f"{slug}.md").write_text(render_markdown(region, week, items), encoding="utf-8")
    logger.info("Wrote regional briefs for week %s to %s", week.date(), folder)
    return folder
