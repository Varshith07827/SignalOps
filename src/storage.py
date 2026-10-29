"""Local persistence with DuckDB.

* Analytics database (``data/generated/storepulse.duckdb``) holds processed
  records, cases, emerging signals and run metadata. It is rebuilt by the
  pipeline.
* State database (``data/state/case_state.duckdb``) holds user-entered case
  status, owner overrides, verification state and an audit log. It is kept
  separate so that re-processing data does not erase workflow history.

Connections are short-lived (open, use, close) so the Streamlit app never
holds a lock that blocks the pipeline - important on Windows.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

import config
from src.taxonomy import OWNERS

LIST_COLUMNS = ("entities", "evidence_ids")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _quote_identifier(name: str) -> str:
    """Validate and quote an internal DuckDB identifier before interpolation."""
    if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"Invalid database identifier: {name!r}")
    return f'"{name}"'


@contextmanager
def connect(path: Path, read_only: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    con.execute("SET enable_progress_bar = false")
    try:
        yield con
    finally:
        con.close()


def _to_storable(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object and len(out) and isinstance(out[col].iloc[0], (list, tuple, set, frozenset)):
            out[col] = out[col].map(lambda v: json.dumps(sorted(v) if isinstance(v, (set, frozenset)) else list(v)))
    return out


def _fetch_df(result) -> pd.DataFrame:
    """Fetch a query result via Arrow (much faster than the direct pandas path)."""
    fetch = getattr(result, "to_arrow_table", None) or getattr(result, "fetch_arrow_table", None)
    return fetch().to_pandas() if fetch else result.df()


def write_tables(tables: dict[str, pd.DataFrame], path: Path = config.ANALYTICS_DB_PATH) -> None:
    with connect(path) as con:
        for name, df in tables.items():
            frame = _to_storable(df)
            con.register("_frame", frame)
            con.execute(f"CREATE OR REPLACE TABLE {_quote_identifier(name)} AS SELECT * FROM _frame")
            con.unregister("_frame")


def read_table(name: str, path: Path = config.ANALYTICS_DB_PATH) -> pd.DataFrame:
    with connect(path, read_only=True) as con:
        return _fetch_df(con.execute(f"SELECT * FROM {_quote_identifier(name)}"))


def query(sql: str, params=None, path: Path = config.ANALYTICS_DB_PATH) -> pd.DataFrame:
    with connect(path, read_only=True) as con:
        return _fetch_df(con.execute(sql, params or []))


def table_exists(name: str, path: Path = config.ANALYTICS_DB_PATH) -> bool:
    _quote_identifier(name)
    if not path.exists():
        return False
    with connect(path, read_only=True) as con:
        return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                                [name]).fetchone()[0])


def write_meta(meta: dict, path: Path = config.ANALYTICS_DB_PATH) -> None:
    write_tables({"run_meta": pd.DataFrame([{"key": k, "value": json.dumps(v, default=str)}
                                            for k, v in meta.items()])}, path)


def read_meta(path: Path = config.ANALYTICS_DB_PATH) -> dict:
    if not table_exists("run_meta", path):
        return {}
    df = read_table("run_meta", path)
    return {k: json.loads(v) for k, v in zip(df["key"], df["value"])}


# --------------------------------------------------------------------------- #
# Case workflow state
# --------------------------------------------------------------------------- #
def init_state(path: Path = config.STATE_DB_PATH) -> None:
    with connect(path) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS case_state (
                case_id VARCHAR PRIMARY KEY,
                status VARCHAR NOT NULL,
                owner VARCHAR,
                verification VARCHAR NOT NULL,
                note VARCHAR,
                updated_at TIMESTAMP NOT NULL
            )""")
        con.execute("""
            CREATE TABLE IF NOT EXISTS case_events (
                case_id VARCHAR NOT NULL,
                event_time TIMESTAMP NOT NULL,
                actor VARCHAR,
                field VARCHAR,
                old_value VARCHAR,
                new_value VARCHAR,
                note VARCHAR
            )""")


def get_case_states(path: Path = config.STATE_DB_PATH) -> pd.DataFrame:
    init_state(path)
    with connect(path, read_only=True) as con:
        return con.execute("SELECT * FROM case_state").df()


def update_case(case_id: str, status: str | None = None, owner: str | None = None,
                verification: str | None = None, note: str | None = None, actor: str = "local user",
                path: Path = config.STATE_DB_PATH) -> dict:
    """Persist a status / owner / verification change and append audit events."""
    if not isinstance(case_id, str) or not case_id.strip() or len(case_id) > 128:
        raise ValueError("case_id must be a non-empty string of at most 128 characters")
    if status is not None and status not in config.CASE_STATUSES:
        raise ValueError(f"Invalid status {status!r}")
    if owner is not None and owner not in OWNERS:
        raise ValueError(f"Invalid owner {owner!r}")
    if verification is not None and verification not in config.VERIFICATION_STATES:
        raise ValueError(f"Invalid verification state {verification!r}")
    if note is not None and len(note) > 2000:
        raise ValueError("note must be at most 2,000 characters")
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 128:
        raise ValueError("actor must be a non-empty string of at most 128 characters")
    init_state(path)
    now = datetime.now().replace(microsecond=0)
    with connect(path) as con:
        row = con.execute("SELECT status, owner, verification, note FROM case_state WHERE case_id = ?",
                          [case_id]).fetchone()
        old = dict(zip(("status", "owner", "verification", "note"),
                       row or ("New", None, config.VERIFICATION_STATES[0], None)))
        new = {
            "status": status if status is not None else old["status"],
            "owner": owner if owner is not None else old["owner"],
            "verification": verification if verification is not None else old["verification"],
            "note": note if note else old["note"],
        }
        con.execute("""INSERT OR REPLACE INTO case_state VALUES (?, ?, ?, ?, ?, ?)""",
                    [case_id, new["status"], new["owner"], new["verification"], new["note"], now])
        for field in ("status", "owner", "verification"):
            if new[field] != old[field]:
                con.execute("INSERT INTO case_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                            [case_id, now, actor, field, old[field], new[field], note])
        if note and not any(new[f] != old[f] for f in ("status", "owner", "verification")):
            con.execute("INSERT INTO case_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [case_id, now, actor, "note", None, None, note])
    return new


def case_history(case_id: str, path: Path = config.STATE_DB_PATH) -> pd.DataFrame:
    init_state(path)
    with connect(path, read_only=True) as con:
        return con.execute("SELECT * FROM case_events WHERE case_id = ? ORDER BY event_time",
                           [case_id]).df()


def reset_state(path: Path = config.STATE_DB_PATH) -> None:
    if path.exists():
        path.unlink()
    init_state(path)
