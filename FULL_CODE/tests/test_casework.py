"""The case workflow: report, start, solve, store confirmation, and the inbox messages each step sends."""

import pytest

from voice_of_store import casework
from voice_of_store.accounts import authenticate, save_user
from voice_of_store.database import apply_schema, session

REPORT = {
    "issue_type_id": "IT10",
    "severity": "high",
    "team": "Store Ops",
    "problem": "Refrigeration",
    "text": "chiller not cooling since 7am",
    "due_at": "2026-01-09T10:00:00",
}
FEEDBACK_CASE = {
    "ref": "FB-000001",
    "store_id": None,
    "issue_type_id": "IT26",
    "severity": "medium",
    "team": "Digital",
    "quote": "app crashes at checkout",
    "opened": "2026-01-06T09:00",
    "due": None,
}


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "app.db"
    apply_schema(path)
    with session(path) as connection:
        save_user(connection, "head-office", "Head office", "admin-pass-1", "admin")
        save_user(connection, "kothrud", "Kothrud manager", "store-pass-1", "store", "ST-AAAAA")
    return path


def _users(connection):
    return authenticate(connection, "head-office", "admin-pass-1"), authenticate(connection, "kothrud", "store-pass-1")


def test_store_report_reaches_head_office(db):
    with session(db) as connection:
        _, store = _users(connection)
        ref = casework.report_problem(connection, store, REPORT, "Saffron Hyper Kothrud")
        second = casework.report_problem(connection, store, REPORT, "Saffron Hyper Kothrud")
        assert (ref, second) == ("R-00001", "R-00002")
        case = casework.case_record(connection, ref)
        assert case["status"] == "open" and case["store_id"] == "ST-AAAAA" and case["summary"] == REPORT["text"]
        inbox = casework.inbox(connection, "admin")
        assert casework.unread_count(connection, "admin") == 2
        assert "New report from Saffron Hyper Kothrud: Refrigeration (high)" in inbox[-1]["body"]
        assert [r["ref"] for r in casework.store_reports(connection, "ST-AAAAA")] == ["R-00002", "R-00001"]
        assert casework.store_reports(connection, "ST-BBBBB") == []


def test_solved_case_closes_only_when_the_store_confirms(db):
    with session(db) as connection:
        admin, store = _users(connection)
        ref = casework.report_problem(connection, store, REPORT, "Kothrud")
        casework.start_work(connection, admin, ref, "technician booked")
        assert casework.resolve(connection, admin, ref, "compressor replaced", "Refrigeration", "Kothrud") == (
            "awaiting_confirmation"
        )
        request = casework.inbox(connection, "ST-AAAAA")[0]
        assert request["kind"] == "confirm_request" and "Is it fixed" in request["body"]
        assert casework.confirm(connection, store, ref, True, "", "Refrigeration", "Kothrud") == "closed"
        assert casework.inbox(connection, "ST-AAAAA")[0]["answered_at"] is not None
        assert casework.inbox(connection, "admin")[0]["kind"] == "confirmed"
        kinds = [event["kind"] for event in casework.timeline(connection, ref)]
        assert kinds == ["reported", "started", "resolved", "confirmed"]
        assert casework.closed_cases(connection)["ST-AAAAA"]["issue_type_id"] == "IT10"


def test_not_fixed_reopens_the_case_with_the_store_comment(db):
    with session(db) as connection:
        admin, store = _users(connection)
        ref = casework.report_problem(connection, store, REPORT, "Kothrud")
        casework.resolve(connection, admin, ref, "door seal changed", "Refrigeration", "Kothrud")
        assert casework.confirm(connection, store, ref, False, "still warm", "Refrigeration", "Kothrud") == "reopened"
        assert "not fixed: still warm" in casework.inbox(connection, "admin")[0]["body"]
        casework.start_work(connection, admin, ref)
        assert casework.case_record(connection, ref)["status"] == "in_progress"


def test_steps_out_of_order_are_refused(db):
    with session(db) as connection:
        admin, store = _users(connection)
        ref = casework.report_problem(connection, store, REPORT, "Kothrud")
        with pytest.raises(casework.CaseError, match="not asked for a confirmation"):
            casework.confirm(connection, store, ref, True, "", "Refrigeration", "Kothrud")
        casework.resolve(connection, admin, ref, "fixed", "Refrigeration", "Kothrud")
        with pytest.raises(casework.CaseError, match="already waiting for store"):
            casework.resolve(connection, admin, ref, "fixed again", "Refrigeration", "Kothrud")
        with pytest.raises(casework.CaseError, match="can't start"):
            casework.start_work(connection, admin, ref)
        with pytest.raises(casework.CaseError) as missing:
            casework.add_note(connection, admin, "R-99999", "hello")
        assert missing.value.status_code == 404


def test_feedback_case_is_saved_on_first_action_and_closes_without_a_store(db):
    with session(db) as connection:
        admin, _ = _users(connection)
        assert casework.statuses(connection, ["FB-000001"]) == {}
        casework.ensure_feedback_case(connection, FEEDBACK_CASE)
        casework.ensure_feedback_case(connection, FEEDBACK_CASE)
        assert casework.statuses(connection, ["FB-000001", "FB-000002"]) == {"FB-000001": "open"}
        assert casework.resolve(connection, admin, "FB-000001", "hotfix released", "App bug", "Online") == "closed"


def test_inbox_read_marks_only_your_own_messages(db):
    with session(db) as connection:
        admin, store = _users(connection)
        ref = casework.report_problem(connection, store, REPORT, "Kothrud")
        casework.resolve(connection, admin, ref, "fixed", "Refrigeration", "Kothrud")
        admin_message = casework.inbox(connection, "admin")[0]["id"]
        casework.mark_read(connection, "ST-AAAAA", admin_message)
        assert casework.unread_count(connection, "admin") == 1
        casework.mark_read(connection, "ST-AAAAA")
        assert casework.unread_count(connection, "ST-AAAAA") == 0
        assert casework.unread_count(connection, "admin") == 1
