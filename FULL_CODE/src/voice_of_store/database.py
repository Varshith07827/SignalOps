"""SQLite connection helpers for the app database (accounts, sessions, cases, inbox)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


def now() -> str:
    """Local time to the second, the same format as the feedback's created_at."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def connect(path: Path) -> sqlite3.Connection:
    # One short-lived connection per request; the timeout waits for a writer instead of failing at once.
    # FastAPI may open it in one worker thread and use it in another, but never from two at the same time.
    connection = sqlite3.connect(path, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def session(path: Path) -> Iterator[sqlite3.Connection]:
    """A connection that commits on success and rolls back on any error."""
    connection = connect(path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def apply_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with session(path) as connection:
        connection.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
