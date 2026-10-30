"""Build everything: submission files, routed records, regional briefs and the cross-validation report.

python FULL_CODE/main.py            # submission/ + FULL_CODE/outputs/
python FULL_CODE/main.py --cv       # also 5-fold cross-validation (adds ~1 minute)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from voice_of_store.cli import configure_logging  # noqa: E402
from voice_of_store.config import load_settings  # noqa: E402
from voice_of_store.data_io import DataValidationError  # noqa: E402
from voice_of_store.evaluation import cross_validate  # noqa: E402
from voice_of_store.pipeline import replay_weekly_flags, run_engine  # noqa: E402
from voice_of_store.reports import write_briefs, write_dashboard_tables, write_submission  # noqa: E402

logger = logging.getLogger("main")


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Build the R5 submission and the weekly regional briefs.")
    parser.add_argument("--data-dir", type=Path, default=None, help="folder with the pack's CSV files")
    parser.add_argument("--cv", action="store_true", help="also run 5-fold cross-validation")
    args = parser.parse_args(argv)

    settings = load_settings()
    data_dir = args.data_dir or settings.paths.data_dir
    try:
        run = run_engine(data_dir, settings)
    except DataValidationError as error:
        logger.error("Input data problem: %s (put the pack's CSV files in %s)", error, data_dir)
        return 2
    # Same flags as running detect.py once per week (tests/test_pipeline.py checks this).
    flags = replay_weekly_flags(run.data, settings)

    write_submission(run.records, flags, settings.paths.submission_dir)
    write_dashboard_tables(run.records, flags, settings.paths.outputs_dir)
    write_briefs(run, flags, settings)
    if args.cv:
        report = cross_validate(run.data, settings)
        path = settings.paths.outputs_dir / "cv_report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("Cross-validation report: %s", report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
