"""Head office tools: upload another feedback file, model accuracy and the official evaluate.py score."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from api.deps import Admin, State
from api.routes_dashboard import status
from voice_of_store.scoring import EvaluationError, EvaluationResult, render_report, run_evaluation
from voice_of_store.service import UploadError, parse_feedback_upload

router = APIRouter(prefix="/api")


def _evaluation_json(result: EvaluationResult) -> dict:
    return {
        "finished_at": result.finished_at,
        "seconds": result.seconds,
        "summary": result.summary,
        "output": result.output,
    }


@router.post("/upload")
def upload(file: Annotated[UploadFile, File()], user: Admin, state: State) -> dict:
    engine, _ = state.ready()
    max_bytes = state.settings.server.max_upload_mb * 1024 * 1024
    content = file.file.read(max_bytes + 1)
    try:
        feedback = parse_feedback_upload(file.filename or "", content, max_bytes)
        analysis = engine.analyse(feedback, file.filename or "Uploaded file")
    except UploadError as error:
        raise HTTPException(400, str(error)) from error
    with state.lock:
        state.current = analysis
    return status(user, state)


@router.post("/dataset")
def show_dataset(user: Admin, state: State) -> dict:
    state.ready()
    with state.lock:
        state.current = state.dataset
    return status(user, state)


@router.get("/accuracy")
def accuracy(_: Admin, state: State) -> dict:
    engine, _ = state.ready()
    return engine.quality()


@router.post("/evaluate")
def evaluate(_: Admin, state: State) -> dict:
    if not state.evaluating.acquire(blocking=False):
        raise HTTPException(409, "evaluate.py is already running.")
    try:
        taxonomy = state.engine.reference.taxonomy if state.engine else None
        result = run_evaluation(state.settings, taxonomy)
    except EvaluationError as error:
        raise HTTPException(400, str(error)) from error
    finally:
        state.evaluating.release()
    state.evaluation = result
    return _evaluation_json(result)


@router.get("/evaluate")
def last_evaluation(_: Admin, state: State) -> dict | None:
    # None until evaluate.py has been run since the server started.
    return _evaluation_json(state.evaluation) if state.evaluation else None


@router.get("/report")
def report(_: Admin, state: State) -> HTMLResponse:
    if state.evaluation is None:
        raise HTTPException(404, "Run evaluate.py first, then download the report.")
    filename = f"voice_of_store_evaluation_{state.evaluation.finished_at[:10]}.html"
    return HTMLResponse(
        render_report(state.evaluation),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
