"""FastAPI app for the dashboard: JSON endpoints plus the static page in FULL_CODE/web/.

Only routing and input checks live here. The analysis code is in voice_of_store.service and .insights.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from voice_of_store.config import Settings
from voice_of_store.data_io import DataValidationError
from voice_of_store.insights import (
    ESCALATION_RULE,
    case_list,
    early_warnings,
    load_store_locations,
    region_top_issues,
    review_result,
    store_map,
    week_label,
    week_overview,
)
from voice_of_store.scoring import EvaluationError, EvaluationResult, render_report, run_evaluation
from voice_of_store.service import Analysis, Engine, UploadError, parse_feedback_upload

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
SECURITY_HEADERS = {
    # Outside sources: Google Fonts (Archivo), Leaflet from unpkg and Esri map tiles. Without internet the page
    # falls back to system fonts and hides the map.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' https://unpkg.com; "
        "img-src 'self' data: https://server.arcgisonline.com; "
        "style-src 'self' https://fonts.googleapis.com https://unpkg.com; font-src https://fonts.gstatic.com"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class NewReview(BaseModel):
    """A message typed into the dashboard's "Check a new review" form."""

    text: str = Field(min_length=3, max_length=2000)
    channel: Literal["online_review", "in_app", "staff_shift_note", "call_centre_ticket"]
    store_id: str | None = Field(default=None, max_length=20)
    rating: int | None = Field(default=None, ge=1, le=5)


class DashboardState:
    """Holds the trained engine and the analysis currently shown. It's a local single-user app."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.engine: Engine | None = None
        self.dataset: Analysis | None = None
        self.current: Analysis | None = None
        self.evaluation: EvaluationResult | None = None
        self.evaluating = threading.Lock()
        self.status = "loading"
        self.message = "Loading the R5 dataset..."

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


def _ready(state: DashboardState) -> tuple[Engine, Analysis]:
    with state.lock:
        engine, current = state.engine, state.current
    if engine is None or current is None:
        raise HTTPException(503, state.message or "Still loading the data. Try again in a moment.")
    return engine, current


def _week(analysis: Analysis, week: str) -> pd.Timestamp:
    for candidate in analysis.weeks:
        if week_label(candidate) == week:
            return candidate
    raise HTTPException(400, "Pick a week from the list.")


def _region(analysis: Analysis, region: str) -> None:
    if region not in analysis.regions:
        raise HTTPException(400, "Pick a region from the list.")


def _evaluation_json(result: EvaluationResult) -> dict:
    return {
        "finished_at": result.finished_at,
        "seconds": result.seconds,
        "summary": result.summary,
        "output": result.output,
    }


def create_app(settings: Settings, make_engine: Callable[[], Engine] | None = None) -> FastAPI:
    state = DashboardState()
    build = make_engine or (lambda: Engine(settings))
    max_bytes = settings.server.max_upload_mb * 1024 * 1024
    locations = load_store_locations()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Training takes a few seconds, so do it in the background and let the page poll /api/status.
        threading.Thread(target=state.prepare, args=(build,), daemon=True).start()
        yield

    app = FastAPI(title="Voice-of-Store dashboard", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.get("/api/status")
    def status() -> dict:
        with state.lock:
            current, dataset = state.current, state.dataset
        if current is None:
            return {"status": state.status, "message": state.message}
        return {
            "status": "ready",
            "dataset": current.name,
            "uploaded": current is not dataset,
            "rows": len(current.records),
            "weeks": [week_label(w) for w in current.weeks],
            "regions": current.regions,
        }

    @app.post("/api/upload")
    def upload(file: Annotated[UploadFile, File()]) -> dict:
        engine, _ = _ready(state)
        content = file.file.read(max_bytes + 1)
        try:
            feedback = parse_feedback_upload(file.filename or "", content, max_bytes)
            analysis = engine.analyse(feedback, file.filename or "Uploaded file")
        except UploadError as error:
            raise HTTPException(400, str(error)) from error
        with state.lock:
            state.current = analysis
        return status()

    @app.post("/api/dataset")
    def show_dataset() -> dict:
        _ready(state)
        with state.lock:
            state.current = state.dataset
        return status()

    @app.get("/api/week")
    def week(week: str, region: str | None = None) -> dict:
        _, current = _ready(state)
        if region is not None:
            _region(current, region)
        return week_overview(current, _week(current, week), region)

    @app.get("/api/cases")
    def cases(
        week: str,
        team: str | None = None,
        region: str | None = None,
        store: str | None = None,
        issue: str | None = None,
    ) -> dict:
        engine, current = _ready(state)
        data = engine.reference
        if region is not None:
            _region(current, region)
        if team is not None and team not in set(data.taxonomy["owner_function"]):
            raise HTTPException(400, "Pick a team from the list.")
        if store is not None and store not in set(data.stores["store_id"]):
            raise HTTPException(400, "Pick a store from the list.")
        if issue is not None and issue not in data.taxonomy.index:
            raise HTTPException(400, "Pick a problem from the list.")
        picked = _week(current, week)
        quote_chars = settings.brief.quote_max_chars
        return case_list(
            current, picked, data.taxonomy, data.stores, quote_chars, team=team, region=region, store=store,
            issue_type_id=issue,
        )  # fmt: skip

    @app.get("/api/map")
    def map_pins(week: str) -> list[dict]:
        engine, current = _ready(state)
        data = engine.reference
        quiet_weeks = settings.brief.solved_after_quiet_weeks
        return store_map(current, _week(current, week), data.taxonomy, data.stores, locations, quiet_weeks)

    @app.get("/api/top-issues")
    def top_issues(region: str, week: str) -> list[dict]:
        engine, current = _ready(state)
        _region(current, region)
        data = engine.reference
        return region_top_issues(current, region, _week(current, week), data.taxonomy, data.stores, settings.brief)

    @app.get("/api/warnings")
    def warnings() -> list[dict]:
        engine, current = _ready(state)
        data = engine.reference
        return early_warnings(current, data.taxonomy, data.stores, settings.brief.quote_max_chars)

    @app.get("/api/stores")
    def stores() -> list[dict]:
        engine, _ = _ready(state)
        table = engine.reference.stores.sort_values(["region", "store_name"])
        return [
            {"store_id": r.store_id, "name": r.store_name, "region": r.region} for r in table.itertuples(index=False)
        ]

    @app.post("/api/review")
    def check_review(review: NewReview) -> dict:
        engine, _ = _ready(state)
        text = review.text.strip()
        if len(text) < 3:
            raise HTTPException(400, "Type at least a few words.")
        data = engine.reference
        if review.store_id and review.store_id not in set(data.stores["store_id"]):
            raise HTTPException(400, "Pick a store from the list.")
        label = engine.classify_review(text, review.channel, review.store_id, review.rating)
        return review_result(label, data.taxonomy, data.stores, settings.routing)

    @app.get("/api/escalation-rule")
    def escalation_rule() -> list[dict]:
        return ESCALATION_RULE

    @app.get("/api/accuracy")
    def accuracy() -> dict:
        engine, _ = _ready(state)
        return engine.quality()

    @app.post("/api/evaluate")
    def evaluate() -> dict:
        if not state.evaluating.acquire(blocking=False):
            raise HTTPException(409, "evaluate.py is already running.")
        try:
            taxonomy = state.engine.reference.taxonomy if state.engine else None
            result = run_evaluation(settings, taxonomy)
        except EvaluationError as error:
            raise HTTPException(400, str(error)) from error
        finally:
            state.evaluating.release()
        state.evaluation = result
        return _evaluation_json(result)

    @app.get("/api/evaluate")
    def last_evaluation() -> dict | None:
        # None until evaluate.py has been run since the server started.
        return _evaluation_json(state.evaluation) if state.evaluation else None

    @app.get("/api/report")
    def report() -> HTMLResponse:
        if state.evaluation is None:
            raise HTTPException(404, "Run evaluate.py first, then download the report.")
        filename = f"voice_of_store_evaluation_{state.evaluation.finished_at[:10]}.html"
        return HTMLResponse(
            render_report(state.evaluation),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
