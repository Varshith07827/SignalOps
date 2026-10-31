"""Sign in, sign out and "who am I"."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from api.deps import SESSION_COOKIE, Db, State
from voice_of_store.accounts import User, authenticate, end_session, has_users, session_user, start_session

router = APIRouter(prefix="/api")


class LoginForm(BaseModel):
    username: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9-]+$")
    password: str = Field(min_length=1, max_length=200)


def _profile(user: User, state: State) -> dict:
    profile = {"username": user.username, "name": user.display_name, "role": user.role, "store": None}
    if user.store_id and state.engine is not None:
        stores = state.engine.reference.stores.set_index("store_id")
        if user.store_id in stores.index:
            row = stores.loc[user.store_id]
            profile["store"] = {
                "store_id": user.store_id,
                "name": str(row["store_name"]),
                "city": str(row["city"]),
                "region": str(row["region"]),
                "format": str(row["format"]),
            }
    return profile


@router.get("/setup")
def setup(connection: Db) -> dict:
    """Whether db/seed.py has created the accounts yet (shown on the sign-in screen)."""
    return {"accounts": has_users(connection)}


@router.post("/login")
def login(form: LoginForm, response: Response, connection: Db, state: State) -> dict:
    wait = state.throttle.seconds_locked(form.username)
    if wait:
        raise HTTPException(429, f"Too many wrong passwords. Try again in {wait // 60 + 1} minutes.")
    user = authenticate(connection, form.username, form.password)
    if user is None:
        state.throttle.failed(form.username)
        raise HTTPException(401, "Wrong username or password.")
    state.throttle.succeeded(form.username)
    with connection:
        token = start_session(connection, user, state.settings.auth.session_hours)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=state.settings.auth.session_hours * 3600,
        httponly=True,
        samesite="strict",
        secure=state.settings.auth.secure_cookies,
    )
    return _profile(user, state)


@router.post("/logout")
def logout(request: Request, response: Response, connection: Db) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with connection:
            end_session(connection, token)
    response.delete_cookie(SESSION_COOKIE)
    return {"signed_out": True}


@router.get("/me")
def me(request: Request, connection: Db, state: State) -> dict | None:
    """The signed-in user, or None (not an error) so the page can simply show the sign-in screen."""
    token = request.cookies.get(SESSION_COOKIE)
    user = session_user(connection, token) if token else None
    return _profile(user, state) if user else None
