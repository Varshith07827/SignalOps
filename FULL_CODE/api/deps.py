"""Shared state and FastAPI dependencies: the loaded engine, a database connection and the signed-in user.

Every permission check happens here, on the server. The page only hides what a user can't do.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from typing import Annotated

import pandas as pd
from fastapi import Depends, HTTPException, Request

from voice_of_store.accounts import LoginThrottle, User, session_user
from voice_of_store.config import Settings
from voice_of_store.data_io import DataValidationError
from voice_of_store.database import connect
from voice_of_store.insights import load_store_locations, week_label
from voice_of_store.scoring import EvaluationResult
from voice_of_store.service import Analysis, Engine

logger = logging.getLogger(__name__)

SESSION_COOKIE = "vos_session"


class AppState:
    """The trained engine and the analysis currently shown (the R5 dataset or an upload)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock = threading.Lock()
        self.engine: Engine | None = None
        self.dataset: Analysis | None = None
        self.current: Analysis | None = None
        self.evaluation: EvaluationResult | None = None
        self.evaluating = threading.Lock()
        self.status = "loading"
        self.message = "Loading the R5 dataset..."
        self.locations = load_store_locations()
        self.throttle = LoginThrottle(settings.auth.max_failed_logins, settings.auth.lockout_minutes)

    def prepare(self, make_engine: Callable[[], Engine]) -> None:
        try:
            engine = make_engine()
            dataset = engine.analyse_dataset()
        except (DataValidationError, OSError, ValueError, RuntimeError) as error:
            logger.exception("Could not load the data folder")
            self.status, self.message = "error", f"Could not load the data folder: {error}"
            return
        with self.lock:
            self.engine, self.dataset, self.current = engine, dataset, dataset
            self.status, self.message = "ready", ""

    def ready(self) -> tuple[Engine, Analysis]:
        with self.lock:
            engine, current = self.engine, self.current
        if engine is None or current is None:
            raise HTTPException(503, self.message or "Still loading the data. Try again in a moment.")
        return engine, current


def get_state(request: Request) -> AppState:
    return request.app.state.vos


State = Annotated[AppState, Depends(get_state)]


def get_db(state: State) -> Iterator[sqlite3.Connection]:
    # Writes are wrapped in "with connection:" in the routes, so they are committed before the response.
    connection = connect(state.settings.database.path)
    try:
        yield connection
    finally:
        connection.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]


def current_user(request: Request, connection: Db) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    user = session_user(connection, token) if token else None
    if user is None:
        raise HTTPException(401, "Please sign in.")
    return user


def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Only head office can do this.")
    return user


def store_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.store_id is None:
        raise HTTPException(403, "Only store managers can do this.")
    return user


AnyUser = Annotated[User, Depends(current_user)]
Admin = Annotated[User, Depends(admin_user)]
StoreManager = Annotated[User, Depends(store_user)]


def check_store_access(user: User, store_id: str | None) -> None:
    """Head office sees every store; a store manager only their own."""
    if not user.is_admin and store_id != user.store_id:
        raise HTTPException(403, "You can only see your own store.")


def pick_week(analysis: Analysis, week: str) -> pd.Timestamp:
    for candidate in analysis.weeks:
        if week_label(candidate) == week:
            return candidate
    raise HTTPException(400, "Pick a week from the list.")


def check_region(analysis: Analysis, region: str | None) -> None:
    if region is not None and region not in analysis.regions:
        raise HTTPException(400, "Pick a region from the list.")


def check_store(engine: Engine, store_id: str | None) -> None:
    if store_id is not None and store_id not in set(engine.reference.stores["store_id"]):
        raise HTTPException(400, "Pick a store from the list.")


def store_names(engine: Engine) -> dict[str, str]:
    stores = engine.reference.stores
    return dict(zip(stores["store_id"], stores["store_name"], strict=True))


def problem_name(engine: Engine, issue_type_id: str) -> str:
    return str(engine.reference.taxonomy.loc[issue_type_id, "issue_type"])
