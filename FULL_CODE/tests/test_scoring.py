"""Running evaluate.py from the dashboard, with a small stand-in scorer so the pack isn't needed."""

import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from toy_pack import write_pack
from voice_of_store.scoring import EvaluationError, EvaluationResult, render_report, run_evaluation, summarise_score

SCORE = {
    "primary_score": 0.8662,
    "classification_score": 0.9993,
    "issue_type_macro_f1": 1.0,
    "severity_weighted_f1": 0.9983,
    "actionable_f1": 0.9989,
    "lead_score": 0.6667,
    "n_scored": 3000,
    "scored_weeks": "2026-03-30..2026-06-22",
    "n_flags": 15,
    "n_flags_valid": 13,
    "n_flags_rejected": 2,
    "avg_flags_per_week": 1.15,
    "flood_factor": 1.0,
    "precision_statement": {
        "escalated_records": 1780,
        "escalated_truly_actionable": 0.9978,
        "escalated_high_or_critical": 449,
        "escalated_high_or_critical_truly_actionable": 0.9978,
    },
    "incidents": [
        {"incident_id": "EX-1", "issue_type_id": "IT17", "onset_week_start": "2026-04-27",
         "naive_detect_week_start": "2026-05-18", "your_first_matching_flag": "2026-05-04", "lead_weeks": 2,
         "incident_score": 0.6667},
        {"incident_id": "EX-2", "issue_type_id": "IT10", "onset_week_start": "2026-05-04",
         "naive_detect_week_start": "2026-05-25", "your_first_matching_flag": None, "lead_weeks": -2,
         "incident_score": 0.0},
    ],
}  # fmt: skip

FAKE_EVALUATOR = """
import argparse, json, sys
parser = argparse.ArgumentParser()
for name in ["submission", "flags", "truth", "incidents", "feedback", "stores", "out"]:
    parser.add_argument("--" + name)
args = parser.parse_args()
if "{fail}" == "yes":
    print("SUBMISSION FORMAT ERROR: missing rows")
    sys.exit(2)
json.dump({score}, open(args.out, "w"))
print("PRIMARY SCORE (0..1, higher is better): 0.8662")
"""


def _settings_with_fake_evaluator(settings, folder, fail=False):
    write_pack(folder)
    (folder / "emerging_incidents_train.csv").write_text("incident_id\n", encoding="utf-8")
    submission = folder / "submission"
    submission.mkdir()
    for name in ("R5_predictions.csv", "R5_emerging_flags.csv"):
        (submission / name).write_text("x\n", encoding="utf-8")
    evaluator = folder / "evaluate.py"
    evaluator.write_text(FAKE_EVALUATOR.format(fail="yes" if fail else "no", score=repr(SCORE)), encoding="utf-8")
    paths = replace(settings.paths, data_dir=folder, submission_dir=submission, outputs_dir=folder / "outputs")
    return replace(settings, paths=paths, evaluation=replace(settings.evaluation, evaluator_path=evaluator))


def test_summary_names_problems_and_marks_missed_incidents(taxonomy):
    summary = summarise_score(SCORE, taxonomy)
    assert summary["primary"] == 0.8662 and summary["flags_rejected"] == 2
    assert summary["incidents"][0]["problem"] == "Issue 17"
    assert summary["incidents"][1]["ours"] == "Not flagged"
    assert summary["urgent_correct"] == 0.9978


def test_report_escapes_text_and_shows_the_score():
    result = EvaluationResult(summarise_score(SCORE), "<script>alert(1)</script>", "2026-10-30 12:00", 1.2)
    report = render_report(result)
    assert "0.8662" in report and "EX-1" in report
    assert "<script>" not in report and "&lt;script&gt;" in report


def test_run_evaluation_reads_the_score_file(settings, tmp_path, taxonomy):
    result = run_evaluation(_settings_with_fake_evaluator(settings, tmp_path), taxonomy)
    assert result.summary["primary"] == 0.8662
    assert "PRIMARY SCORE" in result.output
    assert result.files["evaluator"].endswith("evaluate.py")


def test_run_evaluation_reports_a_failing_scorer(settings, tmp_path):
    with pytest.raises(EvaluationError, match="exit code 2"):
        run_evaluation(_settings_with_fake_evaluator(settings, tmp_path, fail=True))


def test_run_evaluation_names_missing_files(settings, tmp_path):
    missing = replace(settings.evaluation, evaluator_path=tmp_path / "nowhere" / "evaluate.py")
    with pytest.raises(EvaluationError, match="Missing files"):
        run_evaluation(replace(settings, evaluation=missing))


def test_dashboard_runs_the_scorer_and_offers_the_report(settings, tmp_path):
    app = create_app(_settings_with_fake_evaluator(settings, tmp_path))
    with TestClient(app) as api:
        deadline = time.monotonic() + 60
        while api.get("/api/status").json()["status"] == "loading" and time.monotonic() < deadline:
            time.sleep(0.2)
        assert api.get("/api/report").status_code == 404
        assert api.get("/api/evaluate").json() is None
        result = api.post("/api/evaluate").json()
        assert result["summary"]["primary"] == 0.8662
        assert api.get("/api/evaluate").json()["finished_at"] == result["finished_at"]
        report = api.get("/api/report")
        assert report.status_code == 200 and "attachment" in report.headers["content-disposition"]
        assert "Voice of Store evaluation report" in report.text
