"""Upload parsing, plain-English summaries and the dashboard API on the toy pack."""

import time
from dataclasses import replace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from toy_pack import MONDAYS, write_pack
from voice_of_store.insights import early_warnings, week_overview
from voice_of_store.service import Analysis, UploadError, parse_feedback_upload

HEADER = "feedback_id,channel,created_at,store_id,rating,text\n"
WEEK = pd.Timestamp("2026-01-05")


def test_valid_upload_becomes_feedback_rows():
    content = (HEADER + "FB-1,in_app,2026-01-07T10:00:00,ST-AAAAA,2,freezer warm\n").encode()
    frame = parse_feedback_upload("week.csv", content, max_bytes=10_000)
    assert frame["week_start"].tolist() == [WEEK]


@pytest.mark.parametrize(
    "name, content, message",
    [
        ("data.xlsx", b"x", "Please upload a .csv file."),
        ("data.csv", b"", "The file is empty."),
        ("data.csv", b"x" * 2000, "larger than"),
        ("data.csv", b"feedback_id,text\nFB-1,hi\n", "missing these columns: channel"),
        ("data.csv", HEADER.encode(), "no rows"),
        ("data.csv", (HEADER + "FB-1,fax,2026-01-07T10:00:00,,,hi\n").encode(), "unknown channels"),
    ],
)
def test_bad_uploads_get_a_plain_message(name, content, message):
    with pytest.raises(UploadError, match=message):
        parse_feedback_upload(name, content, max_bytes=1000)


def _analysis() -> Analysis:
    records = pd.DataFrame(
        {
            "feedback_id": ["F1", "F2", "F3", "F4"],
            "week_start": [WEEK, WEEK, WEEK, WEEK + pd.Timedelta(weeks=1)],
            "actionable": [1, 1, 0, 1],
            "severity": ["critical", "low", "low", "high"],
            "owner_function": ["Store Ops", "HR", "Not routed", "HR"],
            "text": ["freezer broke, child fell ill", "queue long", "great service", "rude staff"],
        }
    )
    flags = pd.DataFrame(
        {
            "as_of_week_start": ["2026-01-05", "2026-01-12"],
            "store_id": ["ST-AAAAA", "ST-BBBBB"],
            "issue_type_id": ["IT10", "IT04"],
            "confidence": [0.5, 0.6],
            "evidence_feedback_ids": ["F1;F2", "F4;F2;F1"],
        }
    )
    return Analysis("test", records, flags, [WEEK, WEEK + pd.Timedelta(weeks=1)], ["West"])


def test_week_overview_counts_and_puts_urgent_teams_first():
    overview = week_overview(_analysis(), WEEK)
    assert (overview["messages"], overview["need_action"], overview["urgent"], overview["warnings"]) == (3, 2, 1, 1)
    assert [t["team"] for t in overview["teams"]] == ["Store Ops", "HR"]
    assert overview["teams"][0]["critical"] == 1 and overview["teams"][0]["total"] == 1


def test_early_warnings_are_newest_first_with_store_names(taxonomy, stores):
    warnings = early_warnings(_analysis(), taxonomy, stores, quote_chars=12)
    assert [w["week"] for w in warnings] == ["2026-01-12", "2026-01-05"]
    assert warnings[0]["store"] == "Saffron Express Vashi" and warnings[0]["reports"] == 3
    assert warnings[0]["example"] == "rude staff"
    assert warnings[1]["example"] == "freezer b..."


@pytest.fixture()
def client(tmp_path, settings):
    write_pack(tmp_path)
    toy = replace(settings, paths=replace(settings.paths, data_dir=tmp_path))
    with TestClient(create_app(toy)) as test_client:
        deadline = time.monotonic() + 60
        while test_client.get("/api/status").json()["status"] == "loading" and time.monotonic() < deadline:
            time.sleep(0.2)
        yield test_client, tmp_path


def test_dashboard_api_serves_every_section(client):
    api, _ = client
    status = api.get("/api/status").json()
    assert status["status"] == "ready" and status["regions"] == ["West"]
    spike_week = f"{MONDAYS[8]:%Y-%m-%d}"
    assert spike_week in status["weeks"]
    assert api.get(f"/api/week?week={spike_week}").json()["warnings"] == 1
    west = api.get(f"/api/week?week={spike_week}&region=West").json()
    assert west["warnings"] == 1 and west["need_action"] > 0
    issues = api.get(f"/api/top-issues?region=West&week={spike_week}").json()
    assert issues[0]["early_warning"] and issues[0]["trend"] == "New this week"
    warnings = api.get("/api/warnings").json()
    assert warnings[0]["store"] == "Saffron Hyper Kothrud" and warnings[0]["reports"] >= 2
    assert len(api.get("/api/escalation-rule").json()) == 5


def test_dashboard_api_rejects_bad_input(client):
    api, _ = client
    assert api.get("/api/week?week=1999-01-01").status_code == 400
    assert api.get(f"/api/week?week={MONDAYS[0]:%Y-%m-%d}&region=Mars").status_code == 400
    assert api.get(f"/api/top-issues?region=Mars&week={MONDAYS[0]:%Y-%m-%d}").status_code == 400
    response = api.post("/api/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400 and response.json()["detail"] == "Please upload a .csv file."


def test_upload_replaces_the_data_and_the_dataset_can_be_restored(client):
    api, folder = client
    feedback = pd.read_csv(folder / "feedback.csv")
    first_weeks = feedback[pd.to_datetime(feedback["created_at"]) < MONDAYS[3]]
    uploaded = api.post("/api/upload", files={"file": ("first.csv", first_weeks.to_csv(index=False), "text/csv")})
    assert uploaded.status_code == 200
    assert uploaded.json()["dataset"] == "first.csv" and len(uploaded.json()["weeks"]) == 3
    assert uploaded.json()["uploaded"] is True
    restored = api.post("/api/dataset").json()
    assert restored["rows"] == len(feedback) and restored["uploaded"] is False


def test_page_is_served_with_security_headers(client):
    api, _ = client
    page = api.get("/")
    assert page.status_code == 200 and "Voice of Store" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
