"""Small helpers shared by the command-line entry points."""

from __future__ import annotations

import argparse
import logging
import os

import pandas as pd


def configure_logging() -> None:
    level = os.environ.get("VOS_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def parse_date(value: str) -> pd.Timestamp:
    """argparse type for YYYY-MM-DD dates."""
    try:
        return pd.Timestamp(pd.to_datetime(value, format="%Y-%m-%d"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"expected a YYYY-MM-DD date, got {value!r}") from error
