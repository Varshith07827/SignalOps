"""Upload parsing, plain-English summaries and the dashboard API on the toy pack."""

import time
from dataclasses import replace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from toy_pack import MONDAYS, write_pack
from voice_of_store.insights import (
    case_list,
    early_warnings,
    load_store_locations,
    review_result,
    store_map,
    week_overview,
)
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


def _case_records(rows: list[tuple]) -> pd.DataFrame:
    """Rows of (id, incident, store, type, severity, actionable, owner, created_at, channel)."""
    columns = ["feedback_id", "incident_id", "store", "issue_type_id", "severity", "actionable", "owner_function",
               "created_at", "channel"]  # fmt: skip
    records = pd.DataFrame(rows, columns=columns)
    records["created_at"] = pd.to_datetime(records["created_at"])
    records["week_start"] = records["created_at"].dt.normalize() - pd.to_timedelta(
        records["created_at"].dt.weekday, unit="D"
    )
    records["sla_hours"] = records["severity"].map({"critical": 24, "high": 72, "medium": 168})
    records["region"] = "West"
    records["text"] = "message " + records["feedback_id"]
    return records


def test_case_list_merges_reports_and_puts_urgent_first(taxonomy, stores):
    records = _case_records(
        [
            ("F1", "F1", "ST-AAAAA", "IT10", "high", 1, "Store Ops", "2026-01-06T09:00", "in_app"),
            ("F2", "F1", "ST-AAAAA", "IT10", "critical", 1, "Store Ops", "2026-01-06T11:00", "staff_shift_note"),
            ("F3", "F3", "ST-BBBBB", "IT01", "medium", 1, "Store Ops", "2026-01-07T10:00", "online_review"),
            ("F4", "F4", "ST-BBBBB", "IT02", "high", 1, "HR", "2026-01-07T10:00", "online_review"),
            ("F5", "F5", "ST-BBBBB", "NI01", "low", 0, "Not routed", "2026-01-07T10:00", "online_review"),
        ]
    )
    flags = pd.DataFrame({"as_of_week_start": ["2026-01-05"], "store_id": ["ST-AAAAA"], "issue_type_id": ["IT10"]})
    analysis = Analysis("test", records, flags, [WEEK], ["West"])
    result = case_list(analysis, WEEK, taxonomy, stores, quote_chars=50, team="Store Ops")
    first, second = result["cases"]
    assert first["severity"] == "critical" and first["reports"] == 2 and first["early_warning"]
    assert first["store"] == "Saffron Hyper Kothrud" and first["channels"] == ["App", "Staff note"]
    assert (first["opened"], first["due"]) == ("2026-01-06T09:00", "2026-01-07T09:00")
    assert second["severity"] == "medium" and second["due"] == "2026-01-14T10:00"
    assert result["counts"] == {"critical": 1, "high": 0, "medium": 1, "low": 0}
    # The same list for one store and problem, as the map asks for it. Other weeks are empty.
    one = case_list(analysis, WEEK, taxonomy, stores, quote_chars=50, store="ST-BBBBB", issue_type_id="IT02")
    assert [(c["problem"], c["team"]) for c in one["cases"]] == [("Issue 2", "HR")]
    later = WEEK + pd.Timedelta(weeks=1)
    assert case_list(analysis, later, taxonomy, stores, quote_chars=50, team="HR")["cases"] == []


def test_store_map_shows_this_weeks_problems_and_the_last_one_solved(taxonomy, stores):
    records = _case_records(
        [
            ("F1", "F1", "ST-AAAAA", "IT04", "high", 1, "Store Ops", "2025-12-16T10:00", "in_app"),
            ("F2", "F2", "ST-AAAAA", "IT01", "low", 1, "Store Ops", "2025-12-30T10:00", "in_app"),
            ("F3", "F3", "ST-AAAAA", "IT10", "critical", 1, "Store Ops", "2026-01-06T10:00", "in_app"),
            ("F4", "F3", "ST-AAAAA", "IT10", "high", 1, "Store Ops", "2026-01-06T12:00", "in_app"),
            ("F5", "F5", "ST-AAAAA", "IT05", "low", 1, "Store Ops", "2026-01-20T10:00", "in_app"),
        ]
    )
    flags = pd.DataFrame({"as_of_week_start": ["2026-01-05"], "store_id": ["ST-AAAAA"], "issue_type_id": ["IT10"]})
    analysis = Analysis("test", records, flags, [WEEK], ["West"])
    shops = stores.assign(city="Pune", format="Saffron Market")
    locations = pd.DataFrame({"store_id": ["ST-AAAAA", "ST-BBBBB"], "lat": [18.5, 19.1], "lon": [73.8, 73.0]})
    kothrud, vashi = store_map(analysis, WEEK, taxonomy, shops, locations, quiet_weeks=2)
    assert kothrud["cases"] == 1 and kothrud["urgent"] == 1 and kothrud["worst"] == "critical"
    assert kothrud["problems"] == [{"issue_type_id": "IT10", "problem": "Issue 10", "severity": "critical", "cases": 1}]
    assert kothrud["warnings"] == ["Issue 10"]
    # IT01 was reported last week, so only IT04 has been quiet for two weeks. Later weeks are never used.
    assert kothrud["last_solved"] == {"problem": "Issue 4", "last_report": "2025-12-16", "reports": 1}
    assert vashi["cases"] == 0 and vashi["worst"] is None and vashi["last_solved"] is None


def test_store_locations_are_in_india_and_unique():
    locations = load_store_locations()
    assert locations["store_id"].is_unique and len(locations) == 60
    assert locations["lat"].between(6, 36).all() and locations["lon"].between(68, 98).all()


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
    cases = api.get(f"/api/cases?team=Store Ops&week={spike_week}&region=West").json()
    assert cases["counts"]["high"] + cases["counts"]["critical"] > 0
    spike = api.get(f"/api/cases?store=ST-AAAAA&issue=IT10&week={spike_week}").json()["cases"]
    assert spike and all(c["store"] == "Saffron Hyper Kothrud" for c in spike)
    assert api.get(f"/api/map?week={spike_week}").status_code == 200


def test_dashboard_api_rejects_bad_input(client):
    api, _ = client
    assert api.get("/api/week?week=1999-01-01").status_code == 400
    assert api.get(f"/api/week?week={MONDAYS[0]:%Y-%m-%d}&region=Mars").status_code == 400
    assert api.get(f"/api/top-issues?region=Mars&week={MONDAYS[0]:%Y-%m-%d}").status_code == 400
    monday = f"{MONDAYS[0]:%Y-%m-%d}"
    assert api.get(f"/api/cases?team=Nobody&week={monday}").status_code == 400
    assert api.get(f"/api/cases?store=ST-NOPE&week={monday}").status_code == 400
    assert api.get(f"/api/cases?issue=IT99&week={monday}").status_code == 400
    assert api.get("/api/map?week=1999-01-01").status_code == 400
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


def test_review_result_explains_each_outcome(taxonomy, stores, settings):
    base = {"severity": "high", "confidence": 0.8, "language": "hinglish"}
    acted = review_result({**base, "issue_type_id": "IT10", "actionable": 1, "store": "ST-AAAAA"}, taxonomy, stores,
                          settings.routing)  # fmt: skip
    assert acted["needs_action"] and acted["team"] == "Store Ops" and acted["deadline"] == "72 hours"
    assert acted["store"] == "Saffron Hyper Kothrud" and acted["language"] == "Hinglish"
    praise = review_result({**base, "issue_type_id": "NI01", "actionable": 0, "store": None}, taxonomy, stores,
                           settings.routing)  # fmt: skip
    assert "Praise" in praise["reason"] and praise["store"] == "No store (online or app)"
    no_store = review_result({**base, "issue_type_id": "IT10", "actionable": 0, "store": None}, taxonomy, stores,
                             settings.routing)  # fmt: skip
    assert "Pick the store" in no_store["reason"]


def test_new_review_is_labelled_and_routed(client):
    api, _ = client
    stores = api.get("/api/stores").json()
    assert {s["store_id"] for s in stores} == {"ST-AAAAA", "ST-BBBBB", "ST-CCCCC"}
    review = {"text": "freezer not cold, ice cream melted", "channel": "staff_shift_note", "store_id": "ST-BBBBB"}
    result = api.post("/api/review", json=review).json()
    assert result["issue_type_id"] == "IT10" and result["store"] == "Saffron Market Vashi"
    assert result["severity"] in {"high", "critical"}


def test_new_review_input_is_checked(client):
    api, _ = client
    good = {"text": "freezer not cold", "channel": "in_app"}
    assert api.post("/api/review", json={**good, "store_id": "ST-NOPE"}).status_code == 400
    assert api.post("/api/review", json={**good, "rating": 9}).status_code == 422
    assert api.post("/api/review", json={**good, "channel": "fax"}).status_code == 422
    assert api.post("/api/review", json={**good, "text": "  "}).status_code == 422
    assert api.post("/api/review", json={**good, "text": "    ok    "}).status_code == 400
