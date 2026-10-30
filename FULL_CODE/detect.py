"""Emerging-issue detector for one week (the command in submission/detector_cmd.txt).

    python FULL_CODE/detect.py --feedback <folder>/feedback.csv --as-of YYYY-MM-DD --out <flags.csv>

Reads every input file from the folder that contains --feedback, drops all feedback created after the Sunday of
the --as-of week before doing anything else, trains the classifier on that folder's labelled sample, and writes
the flags for the --as-of week only.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from voice_of_store.cli import configure_logging, parse_date  # noqa: E402
from voice_of_store.config import load_settings  # noqa: E402
from voice_of_store.data_io import DataValidationError  # noqa: E402
from voice_of_store.pipeline import detect_week, monday_of  # noqa: E402

logger = logging.getLogger("detect")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write one week's emerging-issue flags (causal, as-of).")
    parser.add_argument("--feedback", required=True, type=Path, help="path to feedback.csv")
    parser.add_argument("--as-of", required=True, dest="as_of", type=parse_date, help="any day of the week, YYYY-MM-DD")
    parser.add_argument("--out", required=True, type=Path, help="flags CSV to write")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    try:
        flags = detect_week(args.feedback.resolve().parent, args.as_of, load_settings())
    except DataValidationError as error:
        logger.error("Input data problem: %s", error)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    flags.to_csv(args.out, index=False)
    logger.info("As of week %s: wrote %d flags to %s", monday_of(args.as_of).date(), len(flags), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
