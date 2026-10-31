"""The case workflow: store reports, head office actions, store confirmation and the in-app inbox.

open / reopened --start--> in_progress --resolve--> awaiting_confirmation --store says fixed--> closed
                                                                          --store says not fixed--> reopened
A case without a store (online orders, app) closes as soon as head office resolves it.
"""

from __future__ import annotations

import sqlite3

from voice_of_store.accounts import User
from voice_of_store.database import now

STATUS_TEXT = {
    "open": "Open",
    "in_progress": "In progress",
    "awaiting_confirmation": "Waiting for store",
    "closed": "Closed",
    "reopened": "Reopened",
}
EVENT_TEXT = {
    "reported": "Reported",
    "started": "Work started",
    "note": "Note",
    "resolved": "Marked solved",
    "confirmed": "Store confirmed it is fixed",
    "not_fixed": "Store says it is not fixed",
}
MAX_NOTE_CHARS = 1000
CHUNK = 500  # SQLite limits the number of ? placeholders in one query


class CaseError(ValueError):
    """A request the workflow can't accept. The message is shown to the user."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def _row(connection: sqlite3.Connection, ref: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM cases WHERE ref = ?", (ref,)).fetchone()
    if row is None:
        raise CaseError("This case was not found.", 404)
    return row


def _event(connection: sqlite3.Connection, case_id: int, user: User | None, kind: str, note: str = "") -> None:
    connection.execute(
        "INSERT INTO case_events (case_id, at, user_id, kind, note) VALUES (?, ?, ?, ?, ?)",
        (case_id, now(), user.id if user else None, kind, note[:MAX_NOTE_CHARS]),
    )


def _message(connection: sqlite3.Connection, recipient: str, case_id: int, kind: str, body: str) -> None:
    connection.execute(
        "INSERT INTO messages (recipient, case_id, kind, body, created_at) VALUES (?, ?, ?, ?, ?)",
        (recipient, case_id, kind, body, now()),
    )


def _set_status(connection: sqlite3.Connection, case_id: int, status: str) -> None:
    connection.execute("UPDATE cases SET status = ?, updated_at = ? WHERE id = ?", (status, now(), case_id))


def report_problem(
    connection: sqlite3.Connection,
    user: User,
    case: dict,
    store_name: str,
) -> str:
    """Save a problem a store manager reported. ``case`` holds the model's labels; returns the new case ref."""
    stamp = now()
    cursor = connection.execute(
        """
        INSERT INTO cases (ref, source, store_id, issue_type_id, severity, team, summary, status,
                           reported_by, created_at, due_at, updated_at)
        VALUES ('R-' || printf('%05d', (SELECT COALESCE(MAX(id), 0) + 1 FROM cases)),
                'store_report', ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
        """,
        (
            user.store_id,
            case["issue_type_id"],
            case["severity"],
            case["team"],
            case["text"],
            user.id,
            stamp,
            case["due_at"],
            stamp,
        ),
    )
    case_id = cursor.lastrowid
    _event(connection, case_id, user, "reported", case["text"])
    body = f"New report from {store_name}: {case['problem']} ({case['severity']})."
    _message(connection, "admin", case_id, "new_report", body)
    return connection.execute("SELECT ref FROM cases WHERE id = ?", (case_id,)).fetchone()["ref"]


def ensure_feedback_case(connection: sqlite3.Connection, case: dict) -> None:
    """Give a case found in the feedback its own row, the first time someone acts on it."""
    connection.execute(
        """
        INSERT OR IGNORE INTO cases (ref, source, store_id, issue_type_id, severity, team, summary, status,
                                     created_at, due_at, updated_at)
        VALUES (?, 'feedback', ?, ?, ?, ?, ?, 'open', ?, ?, ?)
        """,
        (
            case["ref"],
            case["store_id"],
            case["issue_type_id"],
            case["severity"],
            case["team"],
            case["quote"],
            case["opened"],
            case["due"],
            now(),
        ),
    )


def statuses(connection: sqlite3.Connection, refs: list[str]) -> dict[str, str]:
    """Saved status for each ref that has one. Refs without a row are still open."""
    found = {}
    for start in range(0, len(refs), CHUNK):
        chunk = refs[start : start + CHUNK]
        marks = ",".join("?" * len(chunk))
        rows = connection.execute(f"SELECT ref, status FROM cases WHERE ref IN ({marks})", chunk)
        found.update({row["ref"]: row["status"] for row in rows})
    return found


def start_work(connection: sqlite3.Connection, user: User, ref: str, note: str = "") -> None:
    row = _row(connection, ref)
    if row["status"] not in {"open", "reopened"}:
        raise CaseError(f"Work can't start on a case that is {STATUS_TEXT[row['status']].lower()}.")
    _set_status(connection, row["id"], "in_progress")
    _event(connection, row["id"], user, "started", note)


def add_note(connection: sqlite3.Connection, user: User, ref: str, note: str) -> None:
    row = _row(connection, ref)
    _event(connection, row["id"], user, "note", note)


def resolve(connection: sqlite3.Connection, user: User, ref: str, note: str, problem: str, store_name: str) -> str:
    """Head office marks the case solved and asks the store to confirm. Returns the new status."""
    row = _row(connection, ref)
    if row["status"] in {"awaiting_confirmation", "closed"}:
        raise CaseError(f"This case is already {STATUS_TEXT[row['status']].lower()}.")
    _event(connection, row["id"], user, "resolved", note)
    if row["store_id"] is None:
        _set_status(connection, row["id"], "closed")
        return "closed"
    _set_status(connection, row["id"], "awaiting_confirmation")
    body = f"Head office marked “{problem}” at {store_name} as solved: {note} Is it fixed at your store?"
    _message(connection, row["store_id"], row["id"], "confirm_request", body)
    return "awaiting_confirmation"


def confirm(
    connection: sqlite3.Connection, user: User, ref: str, fixed: bool, comment: str, problem: str, store_name: str
) -> str:
    """The store answers head office's "is it fixed?". Returns the new status."""
    row = _row(connection, ref)
    if row["status"] != "awaiting_confirmation":
        raise CaseError("Head office has not asked for a confirmation on this case.")
    status, kind = ("closed", "confirmed") if fixed else ("reopened", "not_fixed")
    _set_status(connection, row["id"], status)
    _event(connection, row["id"], user, kind, comment)
    connection.execute(
        "UPDATE messages SET answered_at = ?, read_at = COALESCE(read_at, ?) "
        "WHERE case_id = ? AND kind = 'confirm_request' AND answered_at IS NULL",
        (now(), now(), row["id"]),
    )
    if fixed:
        body = f"{store_name} confirmed “{problem}” is fixed."
    else:
        body = f"{store_name} says “{problem}” is not fixed" + (f": {comment}" if comment else ".")
    _message(connection, "admin", row["id"], kind, body)
    return status


def case_record(connection: sqlite3.Connection, ref: str) -> dict | None:
    row = connection.execute("SELECT * FROM cases WHERE ref = ?", (ref,)).fetchone()
    return dict(row) if row else None


def timeline(connection: sqlite3.Connection, ref: str) -> list[dict]:
    rows = connection.execute(
        """
        SELECT case_events.at, case_events.kind, case_events.note, users.display_name, users.role
        FROM case_events JOIN cases ON cases.id = case_events.case_id
        LEFT JOIN users ON users.id = case_events.user_id
        WHERE cases.ref = ? ORDER BY case_events.at, case_events.id
        """,
        (ref,),
    )
    return [
        {
            "at": row["at"],
            "kind": row["kind"],
            "what": EVENT_TEXT[row["kind"]],
            "note": row["note"],
            "by": row["display_name"] or "System",
            "by_head_office": row["role"] == "admin",
        }
        for row in rows
    ]


def store_reports(connection: sqlite3.Connection, store_id: str | None = None) -> list[dict]:
    """Problems reported by stores, newest first; one store's only when ``store_id`` is given."""
    query = (
        "SELECT cases.*, users.display_name AS reporter FROM cases "
        "LEFT JOIN users ON users.id = cases.reported_by WHERE cases.source = 'store_report'"
    )
    params: tuple = ()
    if store_id is not None:
        query += " AND cases.store_id = ?"
        params = (store_id,)
    rows = connection.execute(query + " ORDER BY cases.created_at DESC, cases.id DESC", params)
    return [dict(row) for row in rows]


def closed_cases(connection: sqlite3.Connection) -> dict[str, dict]:
    """The most recently confirmed-fixed case per store, from the workflow (not inferred)."""
    rows = connection.execute(
        """
        SELECT cases.store_id, cases.issue_type_id, cases.updated_at FROM cases
        WHERE cases.status = 'closed' AND cases.store_id IS NOT NULL
        ORDER BY cases.updated_at
        """
    )
    return {row["store_id"]: dict(row) for row in rows}


def inbox(connection: sqlite3.Connection, recipient: str, limit: int = 100) -> list[dict]:
    rows = connection.execute(
        """
        SELECT messages.*, cases.ref, cases.status, cases.store_id FROM messages
        JOIN cases ON cases.id = messages.case_id
        WHERE messages.recipient = ? ORDER BY messages.created_at DESC, messages.id DESC LIMIT ?
        """,
        (recipient, limit),
    )
    return [dict(row) for row in rows]


def unread_count(connection: sqlite3.Connection, recipient: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE recipient = ? AND read_at IS NULL", (recipient,)
    ).fetchone()
    return row["n"]


def mark_read(connection: sqlite3.Connection, recipient: str, message_id: int | None = None) -> None:
    """Mark one message (or all of them) read. A recipient can only touch their own messages."""
    query = "UPDATE messages SET read_at = ? WHERE recipient = ? AND read_at IS NULL"
    params: tuple = (now(), recipient)
    if message_id is not None:
        query += " AND id = ?"
        params += (message_id,)
    connection.execute(query, params)
