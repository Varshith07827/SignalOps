"""Run the organisers' evaluate.py on the submission files and turn its output into a summary and a report."""

from __future__ import annotations

import html
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from voice_of_store.config import FULL_CODE_DIR, Settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = FULL_CODE_DIR.parent
REPORT_CSS = """
body { font: 15px/1.5 "Segoe UI", system-ui, sans-serif; color: #1d2550; max-width: 860px;
       margin: 32px auto; padding: 0 16px; }
h1 { font-size: 26px; margin: 0; }
h2 { font-size: 18px; margin-top: 28px; }
.meta { color: #4a5275; }
.big { font-size: 40px; font-weight: 800; margin: 12px 0 0; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #dde0ec; }
th { font-weight: 600; width: 45%; }
thead th { width: auto; color: #4a5275; }
pre { background: #f6f7fb; padding: 12px; overflow-x: auto; font-size: 12px; }
"""


class EvaluationError(RuntimeError):
    """Raised when evaluate.py can't be run. The message is shown to the user."""


@dataclass(frozen=True)
class EvaluationResult:
    summary: dict
    output: str
    finished_at: str
    seconds: float
    files: dict[str, str] = field(default_factory=dict)


def evaluation_files(settings: Settings) -> dict[str, Path]:
    data = settings.paths.data_dir
    submission = settings.paths.submission_dir
    return {
        "evaluator": settings.evaluation.evaluator_path,
        "predictions": submission / "R5_predictions.csv",
        "flags": submission / "R5_emerging_flags.csv",
        "truth": data / "feedback_labels_train.csv",
        "incidents": data / "emerging_incidents_train.csv",
        "feedback": data / "feedback.csv",
        "stores": data / "store_master.csv",
    }


def evaluate_command(settings: Settings, score_path: Path) -> list[str]:
    files = evaluation_files(settings)
    return [
        sys.executable,
        str(files["evaluator"]),
        "--submission", str(files["predictions"]),
        "--flags", str(files["flags"]),
        "--truth", str(files["truth"]),
        "--incidents", str(files["incidents"]),
        "--feedback", str(files["feedback"]),
        "--stores", str(files["stores"]),
        "--out", str(score_path),
    ]  # fmt: skip


def run_evaluation(settings: Settings, taxonomy: pd.DataFrame | None = None) -> EvaluationResult:
    """Run evaluate.py (no shell, with a timeout) and read the score file it writes."""
    files = evaluation_files(settings)
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        names = ", ".join(_project_path(files[name]) for name in missing)
        raise EvaluationError(f"Missing files: {names}. Run python FULL_CODE/main.py first and check the data folder.")

    folder = settings.paths.outputs_dir / "evaluation"
    folder.mkdir(parents=True, exist_ok=True)
    score_path = folder / "score.json"
    score_path.unlink(missing_ok=True)
    started = time.monotonic()
    try:
        done = subprocess.run(
            evaluate_command(settings, score_path),
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.evaluation.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise EvaluationError(
            f"evaluate.py did not finish within {settings.evaluation.timeout_seconds} seconds."
        ) from error
    output = (done.stdout or "") + (done.stderr or "")
    if done.returncode != 0 or not score_path.is_file():
        logger.error("evaluate.py failed with exit code %d", done.returncode)
        raise EvaluationError(f"evaluate.py stopped with an error (exit code {done.returncode}):\n{output[-2000:]}")

    score = json.loads(score_path.read_text(encoding="utf-8"))
    used = {name: _project_path(path) for name, path in files.items()}
    return EvaluationResult(
        summary=summarise_score(score, taxonomy),
        output=output,
        finished_at=time.strftime("%Y-%m-%d %H:%M"),
        seconds=round(time.monotonic() - started, 1),
        files=used,
    )


def summarise_score(score: dict, taxonomy: pd.DataFrame | None = None) -> dict:
    """Pick the numbers the dashboard shows from evaluate.py's score.json."""
    precision = score.get("precision_statement", {})
    incidents = []
    for incident in score.get("incidents", []):
        type_id = incident["issue_type_id"]
        name = str(taxonomy.loc[type_id, "issue_type"]) if taxonomy is not None and type_id in taxonomy.index else ""
        incidents.append(
            {
                "incident": incident["incident_id"],
                "issue_type_id": type_id,
                "problem": name,
                "onset": incident["onset_week_start"],
                "naive": incident["naive_detect_week_start"],
                "ours": incident.get("your_first_matching_flag") or "Not flagged",
                "lead_weeks": incident["lead_weeks"],
                "score": incident["incident_score"],
            }
        )
    return {
        "primary": score["primary_score"],
        "classification": score["classification_score"],
        "issue_type_f1": score["issue_type_macro_f1"],
        "severity_f1": score["severity_weighted_f1"],
        "actionable_f1": score["actionable_f1"],
        "lead_score": score.get("lead_score"),
        "records_scored": score["n_scored"],
        "scored_weeks": score.get("scored_weeks", ""),
        "flags_scored": score.get("n_flags", 0),
        "flags_valid": score.get("n_flags_valid", 0),
        "flags_rejected": score.get("n_flags_rejected", 0),
        "flags_per_week": score.get("avg_flags_per_week", 0),
        "flood_factor": score.get("flood_factor", 1),
        "incidents": incidents,
        "marked_actionable": precision.get("escalated_records", 0),
        "actionable_correct": precision.get("escalated_truly_actionable", 0),
        "marked_urgent": precision.get("escalated_high_or_critical", 0),
        "urgent_correct": precision.get("escalated_high_or_critical_truly_actionable", 0),
    }


def render_report(result: EvaluationResult) -> str:
    """A self-contained HTML report of one evaluate.py run. All values are escaped."""
    s = result.summary

    def row(label: str, value: object) -> str:
        return f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(value))}</td></tr>"

    scores = "".join(
        row(label, value)
        for label, value in [
            ("Primary score (0 to 1)", f"{s['primary']:.4f}"),
            ("Classification score", f"{s['classification']:.4f}"),
            ("Problem type, macro-F1", f"{s['issue_type_f1']:.4f}"),
            ("Severity, weighted-F1", f"{s['severity_f1']:.4f}"),
            ("Needs action, F1", f"{s['actionable_f1']:.4f}"),
            ("Early-warning lead score", "-" if s["lead_score"] is None else f"{s['lead_score']:.4f}"),
            ("Records scored", s["records_scored"]),
        ]
    )
    flags = "".join(
        row(label, value)
        for label, value in [
            ("Weeks scored", s["scored_weeks"]),
            ("Flags in those weeks", s["flags_scored"]),
            ("Valid / rejected", f"{s['flags_valid']} / {s['flags_rejected']}"),
            ("Flags per week (limit 3)", s["flags_per_week"]),
        ]
    )
    incidents = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(v))}</td>"
            for v in (i["incident"], f"{i['issue_type_id']} {i['problem']}".strip(), i["onset"], i["naive"], i["ours"],
                      f"{i['lead_weeks']:+d}", f"{i['score']:.3f}")
        )
        + "</tr>"
        for i in s["incidents"]
    )  # fmt: skip
    files = "".join(row(name, path) for name, path in result.files.items())
    precision = (
        f"Of {s['marked_actionable']:,} messages marked as needing action, {s['actionable_correct']:.1%} truly did. "
        f"Of {s['marked_urgent']:,} marked as needing action and high or critical, {s['urgent_correct']:.1%} truly did."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Voice of Store evaluation report</title>
<style>{REPORT_CSS}</style></head><body>
<h1>Voice of Store evaluation report</h1>
<p class="meta">Scored with the organisers' evaluate.py on {html.escape(result.finished_at)} ({result.seconds} s).</p>
<p class="big">{s["primary"]:.4f}</p><p class="meta">Primary score = 0.6 x classification + 0.4 x lead score</p>
<h2>Scores</h2><table>{scores}</table>
<h2>Precision statement</h2><p>{html.escape(precision)}</p>
<h2>Early-warning incidents</h2>
<table><thead><tr><th>Incident</th><th>Problem type</th><th>Started</th><th>Simple counter</th><th>Our flag</th>
<th>Weeks earlier</th><th>Score</th></tr></thead><tbody>{incidents}</tbody></table>
<h2>Flag check</h2><table>{flags}</table>
<h2>Files used</h2><table>{files}</table>
<h2>Full evaluate.py output</h2><pre>{html.escape(result.output)}</pre>
</body></html>
"""


def _project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)
