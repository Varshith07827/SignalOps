"""Build and run the project's own commands (detector, full build, scorer) for the dashboard's Run tab.

Commands are fixed argument lists run without a shell; the only values that vary are weeks picked from the
pack's calendar and output paths this module creates, so nothing a user types reaches a command line.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from voice_of_store.config import FULL_CODE_DIR, Settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = FULL_CODE_DIR.parent


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    output: str
    seconds: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def project_path(path: Path) -> str:
    """Path as written from the project root (how the README and detector_cmd.txt spell commands)."""
    try:
        return Path(os.path.relpath(path, PROJECT_ROOT)).as_posix()
    except ValueError:  # different drive on Windows: fall back to the absolute path
        return str(path)


def detector_command(settings: Settings, monday: pd.Timestamp, out: Path) -> list[str]:
    """The submission's detector command for one week."""
    return [
        "python",
        project_path(FULL_CODE_DIR / "detect.py"),
        "--feedback",
        project_path(settings.paths.data_dir / "feedback.csv"),
        "--as-of",
        f"{monday:%Y-%m-%d}",
        "--out",
        project_path(out),
    ]


def build_command(with_cv: bool) -> list[str]:
    command = ["python", project_path(FULL_CODE_DIR / "main.py")]
    return command + ["--cv"] if with_cv else command


def evaluate_command(settings: Settings) -> list[str]:
    """Score submission/ against the public labels with the organisers' evaluate.py."""
    data = settings.paths.data_dir
    return [
        "python",
        project_path(settings.runner.evaluator_path),
        "--submission",
        project_path(settings.paths.submission_dir / "R5_predictions.csv"),
        "--truth",
        project_path(data / "feedback_labels_train.csv"),
        "--feedback",
        project_path(data / "feedback.csv"),
        "--stores",
        project_path(data / "store_master.csv"),
        "--out",
        project_path(settings.paths.outputs_dir / "score_train.json"),
    ]


def display(command: list[str]) -> str:
    return " ".join(command)


def run_command(command: list[str], timeout_seconds: int) -> CommandResult:
    """Run from the project root with this interpreter standing in for ``python``; never raises on failure."""
    argv = [sys.executable, *command[1:]] if command and command[0] == "python" else command
    started = time.monotonic()
    try:
        done = subprocess.run(
            argv,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        output, code = (done.stdout or "") + (done.stderr or ""), done.returncode
    except subprocess.TimeoutExpired:
        output, code = f"Stopped: no result after {timeout_seconds} s.", -1
    except OSError as error:
        output, code = f"Could not start the command: {error}", -1
    seconds = round(time.monotonic() - started, 1)
    logger.info("Ran %s -> exit %d in %.1fs", display(command), code, seconds)
    return CommandResult(command, code, output, seconds)


def weeks_between(calendar_weeks: list[pd.Timestamp], first: pd.Timestamp, last: pd.Timestamp) -> list[pd.Timestamp]:
    """Calendar weeks from ``first`` to ``last`` inclusive; both must be calendar weeks, in order."""
    weeks = sorted(pd.Timestamp(w) for w in calendar_weeks)
    if first not in weeks or last not in weeks:
        raise ValueError("pick weeks from the calendar")
    if first > last:
        raise ValueError("the first week must not be after the last week")
    return [w for w in weeks if first <= w <= last]


def new_run_folder(outputs_dir: Path) -> Path:
    folder = outputs_dir / "runs" / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def compare_with_submission(week_flags: dict[pd.Timestamp, pd.DataFrame], submitted: pd.DataFrame) -> pd.DataFrame:
    """Per week: flags from this run, flags in the submitted file, and whether they are identical."""
    rows = []
    for monday, flags in sorted(week_flags.items()):
        expected = submitted[submitted["as_of_week_start"] == f"{monday:%Y-%m-%d}"].reset_index(drop=True)
        same = len(flags) == len(expected) and flags.astype(str).equals(expected.astype(str))
        rows.append(
            {"week": f"{monday:%Y-%m-%d}", "run_flags": len(flags), "submitted_flags": len(expected), "identical": same}
        )
    return pd.DataFrame(rows, columns=["week", "run_flags", "submitted_flags", "identical"])
