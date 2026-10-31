"""FastAPI app: JSON endpoints plus the static page in FULL_CODE/web/.

Routes live in routes_*.py and hold only input checks and permissions. The analysis and workflow code is in
voice_of_store (service, insights, reputation, casework, accounts).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api import routes_admin, routes_auth, routes_cases, routes_dashboard
from api.deps import AppState
from voice_of_store.config import Settings
from voice_of_store.database import apply_schema
from voice_of_store.service import Engine

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
# Sent by the page on every change request. A form on another site can't add it, which blocks request forgery
# on top of the SameSite=Strict session cookie.
CSRF_HEADER = ("x-requested-with", "voice-of-store")
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


def create_app(settings: Settings, make_engine: Callable[[], Engine] | None = None) -> FastAPI:
    state = AppState(settings)
    build = make_engine or (lambda: Engine(settings))
    apply_schema(settings.database.path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Training takes a few seconds, so do it in the background and let the page poll /api/status.
        threading.Thread(target=state.prepare, args=(build,), daemon=True).start()
        yield

    app = FastAPI(title="Voice of Store", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.vos = state

    @app.middleware("http")
    async def guard(request: Request, call_next):
        changes = request.method not in {"GET", "HEAD", "OPTIONS"}
        if changes and request.url.path.startswith("/api/") and request.headers.get(CSRF_HEADER[0]) != CSRF_HEADER[1]:
            response = JSONResponse({"detail": "This request was blocked. Reload the page and try again."}, 403)
        else:
            response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    for module in (routes_auth, routes_dashboard, routes_cases, routes_admin):
        app.include_router(module.router)
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
