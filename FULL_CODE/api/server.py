"""FastAPI app for the dashboard: JSON endpoints plus the static page in FULL_CODE/web/.

Only routing and input checks live here. The analysis code is in voice_of_store.service and .insights.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from voice_of_store.config import Settings
from voice_of_store.data_io import DataValidationError
from voice_of_store.insights import ESCALATION_RULE, early_warnings, region_top_issues, week_label, week_overview
from voice_of_store.scoring import EvaluationError, EvaluationResult, render_report, run_evaluation
from voice_of_store.service import Analysis, Engine, UploadError, parse_feedback_upload

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
SECURITY_HEADERS = {
    # Google Fonts is the only outside source (the Archivo font). Without internet the page uses system fonts.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; img-src 'self' data:; "
        "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


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
