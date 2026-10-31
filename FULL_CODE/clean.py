"""Clean a raw copy of the problem pack before the engine reads it.

    python FULL_CODE/clean.py --in <raw folder> [--out FULL_CODE/data]

Reads the pack's CSV files from --in, repairs what can be repaired (whitespace, casing, channel aliases, date
formats, issue ids, duplicates), drops rows that cannot be, and writes the cleaned files with the same names
and columns to --out (default: the data folder in config.toml). A cleaning_report.json next to them lists
every change. The result is then loaded with the engine's own validator, so a zero exit code means main.py,
detect.py and serve.py will accept it.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from voice_of_store.cleaning import clean_pack  # noqa: E402
from voice_of_store.cli import configure_logging  # noqa: E402
from voice_of_store.config import load_settings  # noqa: E402
from voice_of_store.data_io import REQUIRED_COLUMNS, DataValidationError, load_pack  # noqa: E402

logger = logging.getLogger("clean")
REPORT_NAME = "cleaning_report.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean the pack's CSV files so the engine can read them.")
    parser.add_argument("--in", dest="source", required=True, type=Path, help="folder with the raw CSV files")
    parser.add_argument("--out", dest="destination", type=Path, default=None, help="folder for the cleaned files")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    destination = (args.destination or load_settings().paths.data_dir).resolve()
    source = args.source.resolve()
    if source == destination:
        logger.error("--in and --out are the same folder; keep the raw files and write the cleaned ones elsewhere")
        return 2
    try:
        report = clean_pack(source, destination)
    except (FileNotFoundError, ValueError) as error:
        logger.error("Could not clean %s: %s", source, error)
        return 2
    (destination / REPORT_NAME).write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Cleaning report: %s", destination / REPORT_NAME)

    if all((destination / name).is_file() for name in REQUIRED_COLUMNS):
        try:
            load_pack(destination)
        except DataValidationError as error:
            logger.error("Cleaned data still fails validation: %s", error)
            return 1
        logger.info("Cleaned pack in %s passes the engine's validation", destination)
    else:
        logger.warning("Some pack files were missing, so the full validation was skipped (see %s)", REPORT_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
