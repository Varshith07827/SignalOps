"""Read-only views of the analysis: weekly numbers, regional brief, early warnings, stores and reputation."""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import Admin, AnyUser, Db, State, check_region, check_store, check_store_access, pick_week
from voice_of_store import casework
from voice_of_store.insights import (
    ESCALATION_RULE,
    early_warnings,
    region_top_issues,
    review_result,
    store_map,
    week_label,
    week_overview,
)
from voice_of_store.reputation import store_reputation

router = APIRouter(prefix="/api")


class NewReview(BaseModel):
    """A message typed into "Check a review"."""

    text: str = Field(min_length=3, max_length=2000)
    channel: Literal["online_review", "in_app", "staff_shift_note", "call_centre_ticket"]
    store_id: str | None = Field(default=None, max_length=20)
    rating: int | None = Field(default=None, ge=1, le=5)


@router.get("/status")
def status(_: AnyUser, state: State) -> dict:
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


@router.get("/week")
def week(_: Admin, state: State, week: str, region: str | None = None) -> dict:
    _, current = state.ready()
    check_region(current, region)
    return week_overview(current, pick_week(current, week), region)


@router.get("/top-issues")
def top_issues(_: Admin, state: State, region: str, week: str) -> list[dict]:
    engine, current = state.ready()
    check_region(current, region)
    data = engine.reference
    return region_top_issues(
        current, region, pick_week(current, week), data.taxonomy, data.stores, state.settings.brief
    )


@router.get("/warnings")
def warnings(_: Admin, state: State) -> list[dict]:
    engine, current = state.ready()
    data = engine.reference
    return early_warnings(current, data.taxonomy, data.stores, state.settings.brief.quote_max_chars)


def _pins(state: State, connection: Db, week: str) -> list[dict]:
    """Every store's week, with "last solved" taken from confirmed fixes where the app has one."""
    engine, current = state.ready()
    data = engine.reference
    quiet = state.settings.brief.solved_after_quiet_weeks
    pins = store_map(current, pick_week(current, week), data.taxonomy, data.stores, state.locations, quiet)
    confirmed = casework.closed_cases(connection)
    for pin in pins:
        fix = confirmed.get(pin["store_id"])
        if fix:
            problem = str(data.taxonomy.loc[fix["issue_type_id"], "issue_type"])
            pin["last_solved"] = {"problem": problem, "last_report": fix["updated_at"][:10], "confirmed": True}
    return pins


@router.get("/map")
def map_pins(_: Admin, state: State, connection: Db, week: str) -> list[dict]:
    return _pins(state, connection, week)


@router.get("/reputation")
def reputation(_: Admin, state: State, week: str) -> list[dict]:
    engine, current = state.ready()
    quote_chars = state.settings.brief.quote_max_chars
    return store_reputation(
        current, pick_week(current, week), engine.reference.stores, state.settings.reputation, quote_chars
    )


@router.get("/stores")
def stores(_: Admin, state: State) -> list[dict]:
    engine, _ = state.ready()
    table = engine.reference.stores.sort_values(["region", "store_name"])
    return [
        {"store_id": r.store_id, "name": r.store_name, "city": r.city, "region": r.region}
        for r in table.itertuples(index=False)
    ]


@router.get("/stores/{store_id}/overview")
def store_overview(store_id: str, user: AnyUser, state: State, connection: Db, week: str) -> dict:
    """One store's week: problems, early warnings, reputation and last solved. Store managers: own store only."""
    check_store_access(user, store_id)
    engine, current = state.ready()
    check_store(engine, store_id)
    pin = next((p for p in _pins(state, connection, week) if p["store_id"] == store_id), None)
    if pin is None:
        raise HTTPException(404, "This store was not found.")
    # Rank every store to find this one's place.
    every_store = replace(state.settings.reputation, top_n=len(engine.reference.stores))
    quote_chars = state.settings.brief.quote_max_chars
    ranking = store_reputation(current, pick_week(current, week), engine.reference.stores, every_store, quote_chars)
    standing = next(
        (
            {**entry, "rank": rank, "of": len(ranking)}
            for rank, entry in enumerate(ranking, 1)
            if entry["store_id"] == store_id
        ),
        None,
    )
    return {"store": pin, "reputation": standing}


@router.get("/escalation-rule")
def escalation_rule(_: AnyUser) -> list[dict]:
    return ESCALATION_RULE


@router.post("/review")
def check_review(review: NewReview, _: Admin, state: State) -> dict:
    engine, _ = state.ready()
    text = review.text.strip()
    if len(text) < 3:
        raise HTTPException(400, "Type at least a few words.")
    check_store(engine, review.store_id or None)
    label = engine.classify_review(text, review.channel, review.store_id or None, review.rating)
    data = engine.reference
    return review_result(label, data.taxonomy, data.stores, state.settings.routing)
