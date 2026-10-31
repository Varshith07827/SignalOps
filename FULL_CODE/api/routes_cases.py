"""Cases: lists, detail, the solve-and-confirm workflow, store reports and the inbox."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import (
    Admin,
    AnyUser,
    Db,
    State,
    StoreManager,
    check_region,
    check_store,
    check_store_access,
    pick_week,
    problem_name,
    store_names,
)
from voice_of_store import casework
from voice_of_store.accounts import User
from voice_of_store.insights import ACTION_TEXT, SEVERITIES, case_list, incident_case, review_result
from voice_of_store.routing import escalation_level, sla_hours

router = APIRouter(prefix="/api")

ACTIVE = "active"  # status filter: everything not closed


class NoteForm(BaseModel):
    note: str = Field(default="", max_length=casework.MAX_NOTE_CHARS)


class ResolveForm(BaseModel):
    note: str = Field(min_length=3, max_length=casework.MAX_NOTE_CHARS)


class ConfirmForm(BaseModel):
    fixed: bool
    comment: str = Field(default="", max_length=casework.MAX_NOTE_CHARS)


class ReportForm(BaseModel):
    text: str = Field(min_length=5, max_length=2000)


def _with_status(case: dict, status: str) -> dict:
    return {**case, "status": status, "status_text": casework.STATUS_TEXT[status]}


def _from_row(row: dict, state: State) -> dict:
    """A case saved in the app database, in the same shape as cases found in the feedback."""
    engine, _ = state.ready()
    store = row["store_id"]
    is_report = row["source"] == "store_report"
    return _with_status(
        {
            "ref": row["ref"],
            "source": row["source"],
            "store_id": store,
            "store": store_names(engine).get(store, store) if store else "Online or app (no store)",
            "issue_type_id": row["issue_type_id"],
            "problem": problem_name(engine, row["issue_type_id"]),
            "team": row["team"],
            "severity": row["severity"],
            "action": ACTION_TEXT[escalation_level(row["severity"], emerging=False)],
            "opened": row["created_at"][:16],
            "due": row["due_at"][:16] if row["due_at"] else None,
            "reports": 1,
            "channels": ["Store report"] if is_report else [],
            "early_warning": False,
            "quote": row["summary"],
            "reporter": row.get("reporter"),
        },
        row["status"],
    )


def _load(state: State, connection: Db, ref: str) -> tuple[dict, dict | None]:
    """The case (with its status) and its database row, if it has one."""
    engine, current = state.ready()
    row = casework.case_record(connection, ref)
    if row and row["source"] == "store_report":
        return _from_row(row, state), row
    data = engine.reference
    found = incident_case(current, ref, data.taxonomy, data.stores, state.settings.brief.quote_max_chars)
    if found is None:
        if row is None:
            raise HTTPException(404, "This case was not found.")
        return _from_row(row, state), row
    return _with_status({**found, "source": "feedback"}, row["status"] if row else "open"), row


def _detail(state: State, connection: Db, user: User, ref: str) -> dict:
    case, _ = _load(state, connection, ref)
    check_store_access(user, case["store_id"])
    status = case["status"]
    if case["source"] == "store_report":
        case["messages"] = [{"at": case["opened"], "channel": "Store report", "language": "", "text": case["quote"]}]
    case["timeline"] = casework.timeline(connection, ref)
    case["can"] = {
        "start": user.is_admin and status in {"open", "reopened"},
        "resolve": user.is_admin and status not in {"awaiting_confirmation", "closed"},
        "confirm": not user.is_admin and status == "awaiting_confirmation",
        "note": True,
    }
    return case


def _act(state: State, connection: Db, user: User, ref: str) -> tuple[dict, str, str]:
    """Load a case for an action: check access, save feedback cases on first use. Returns case, problem, store."""
    case, row = _load(state, connection, ref)
    check_store_access(user, case["store_id"])
    if row is None:
        casework.ensure_feedback_case(connection, case)
    return case, case["problem"], case["store"]


def _run(state: State, connection: Db, user: User, ref: str, action) -> dict:
    with connection:
        try:
            action(*_act(state, connection, user, ref))
        except casework.CaseError as error:
            raise HTTPException(error.status_code, str(error)) from error
    return _detail(state, connection, user, ref)


@router.get("/cases")
def cases(
    user: AnyUser,
    state: State,
    connection: Db,
    week: str,
    team: str | None = None,
    region: str | None = None,
    store: str | None = None,
    issue: str | None = None,
    status: str | None = None,
) -> dict:
    """The week's cases from the feedback, with their workflow status. Store managers see their store only."""
    engine, current = state.ready()
    data = engine.reference
    store = store if user.is_admin else user.store_id
    check_region(current, region)
    check_store(engine, store)
    if team is not None and team not in set(data.taxonomy["owner_function"]):
        raise HTTPException(400, "Pick a team from the list.")
    if issue is not None and issue not in data.taxonomy.index:
        raise HTTPException(400, "Pick a problem from the list.")
    if status is not None and status not in {*casework.STATUS_TEXT, ACTIVE}:
        raise HTTPException(400, "Pick a status from the list.")
    found = case_list(
        current, pick_week(current, week), data.taxonomy, data.stores, state.settings.brief.quote_max_chars,
        team=team, region=region, store=store, issue_type_id=issue,
    )  # fmt: skip
    saved = casework.statuses(connection, [c["ref"] for c in found["cases"]])
    listed = [_with_status({**c, "source": "feedback"}, saved.get(c["ref"], "open")) for c in found["cases"]]
    if status == ACTIVE:
        listed = [c for c in listed if c["status"] != "closed"]
    elif status is not None:
        listed = [c for c in listed if c["status"] == status]
    counts = {s: sum(c["severity"] == s for c in listed) for s in SEVERITIES}
    return {"cases": listed, "counts": counts}


@router.get("/cases/{ref}")
def case_detail(ref: str, user: AnyUser, state: State, connection: Db) -> dict:
    return _detail(state, connection, user, ref)


@router.post("/cases/{ref}/start")
def start(ref: str, form: NoteForm, user: Admin, state: State, connection: Db) -> dict:
    return _run(state, connection, user, ref, lambda *_: casework.start_work(connection, user, ref, form.note))


@router.post("/cases/{ref}/note")
def note(ref: str, form: NoteForm, user: AnyUser, state: State, connection: Db) -> dict:
    if not form.note.strip():
        raise HTTPException(400, "Type a note first.")
    return _run(state, connection, user, ref, lambda *_: casework.add_note(connection, user, ref, form.note.strip()))


@router.post("/cases/{ref}/resolve")
def resolve(ref: str, form: ResolveForm, user: Admin, state: State, connection: Db) -> dict:
    def action(_, problem, store):
        casework.resolve(connection, user, ref, form.note.strip(), problem, store)

    return _run(state, connection, user, ref, action)


@router.post("/cases/{ref}/confirm")
def confirm(ref: str, form: ConfirmForm, user: StoreManager, state: State, connection: Db) -> dict:
    def action(_, problem, store):
        casework.confirm(connection, user, ref, form.fixed, form.comment.strip(), problem, store)

    return _run(state, connection, user, ref, action)


@router.get("/reports")
def reports(user: AnyUser, state: State, connection: Db) -> list[dict]:
    """Problems reported by stores in the app, newest first. Store managers see their own store's."""
    rows = casework.store_reports(connection, None if user.is_admin else user.store_id)
    return [_from_row(row, state) for row in rows]


@router.post("/reports")
def report(form: ReportForm, user: StoreManager, state: State, connection: Db) -> dict:
    """A store manager reports a problem from a staff note. The model labels and routes it."""
    engine, _ = state.ready()
    text = form.text.strip()
    label = engine.classify_review(text, "staff_shift_note", user.store_id, None)
    data = engine.reference
    result = review_result(label, data.taxonomy, data.stores, state.settings.routing)
    if not result["needs_action"]:
        return {"raised": False, "result": result}
    hours = sla_hours(label["severity"], state.settings.routing)
    due = (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S") if hours else None
    case = {**label, "team": result["team"], "problem": result["problem"], "text": text, "due_at": due}
    with connection:
        ref = casework.report_problem(connection, user, case, store_names(engine)[user.store_id])
    return {"raised": True, "result": result, "case": _detail(state, connection, user, ref)}


def _recipient(user: User) -> str:
    return "admin" if user.is_admin else str(user.store_id)


@router.get("/inbox")
def inbox(user: AnyUser, connection: Db) -> dict:
    recipient = _recipient(user)
    messages = [
        {
            "id": m["id"],
            "kind": m["kind"],
            "body": m["body"],
            "at": m["created_at"],
            "read": m["read_at"] is not None,
            "answered": m["answered_at"] is not None,
            "ref": m["ref"],
            "status": m["status"],
            "status_text": casework.STATUS_TEXT[m["status"]],
        }
        for m in casework.inbox(connection, recipient)
    ]
    return {"unread": casework.unread_count(connection, recipient), "messages": messages}


class ReadForm(BaseModel):
    id: int | None = Field(default=None, ge=1)


@router.post("/inbox/read")
def read(form: ReadForm, user: AnyUser, connection: Db) -> dict:
    with connection:
        casework.mark_read(connection, _recipient(user), form.id)
    return {"unread": casework.unread_count(connection, _recipient(user))}
