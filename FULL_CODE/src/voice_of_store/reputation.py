"""Stores customers are happiest with this week, and the reasons, for the "Doing well" panel."""

from __future__ import annotations

import pandas as pd

from voice_of_store.config import ReputationSettings
from voice_of_store.service import Analysis

PRAISE = "NI01"
# Share of the 0-100 score: star rating, compliments, and few complaints for the store's footfall.
WEIGHTS = {"rating": 0.4, "praise": 0.3, "complaints": 0.3}
# Compliment share is pulled toward the chain's as if every store had this many extra messages, so a small
# store with 1 compliment in 3 messages doesn't outrank a big store with 12 in 60.
PRAISE_PRIOR_MESSAGES = 15


def _store_week(rows: pd.DataFrame) -> pd.DataFrame:
    """Per store: messages, compliments, star ratings and complaint cases in these rows."""
    actionable = rows[rows["actionable"] == 1]
    return pd.DataFrame(
        {
            "messages": rows.groupby("store").size(),
            "praise": rows[rows["issue_type_id"] == PRAISE].groupby("store").size(),
            "ratings": rows.groupby("store")["rating"].count(),
            "rating": rows.groupby("store")["rating"].mean(),
            "cases": actionable.groupby("store")["incident_id"].nunique(),
        }
    ).fillna({"messages": 0, "praise": 0, "ratings": 0, "cases": 0})


def _score(table: pd.DataFrame, min_ratings: int) -> pd.Series:
    """0-100 from percentile ranks among this week's stores. Too few ratings: that part is left out."""
    parts = pd.DataFrame(
        {
            "rating": table["rating"].where(table["ratings"] >= min_ratings).rank(pct=True),
            "praise": table["praise_share"].rank(pct=True),
            "complaints": 1 - table["complaint_rate"].rank(pct=True) + 1 / len(table),
        }
    )
    weights = pd.DataFrame({name: parts[name].notna() * weight for name, weight in WEIGHTS.items()})
    return (parts.fillna(0) * weights).sum(axis=1) / weights.sum(axis=1) * 100


def _reasons(row: pd.Series, chain_rating: float, chain_rate: float, min_ratings: int) -> list[str]:
    reasons = []
    if row["ratings"] >= min_ratings:
        reasons.append(f"Rated {row['rating']:.1f}★ by {int(row['ratings'])} customers (chain {chain_rating:.1f}★)")
    if row["praise"]:
        reasons.append(f"{int(row['praise'])} compliment{'s' if row['praise'] != 1 else ''}")
    reasons.append(f"{row['complaint_rate']:.1f} complaints per 1,000 shoppers (chain {chain_rate:.1f})")
    if row["last_cases"] > row["cases"]:
        reasons.append(f"Complaints down from {int(row['last_cases'])} to {int(row['cases'])}")
    return reasons


def _best_praise(rows: pd.DataFrame, store: str, quote_chars: int) -> str | None:
    praise = rows[(rows["store"] == store) & (rows["issue_type_id"] == PRAISE)]
    praise = praise[praise["text"].str.len().between(20, quote_chars)]
    if praise.empty:
        return None
    return str(praise.sort_values("issue_confidence", ascending=False)["text"].iloc[0])


def store_reputation(
    analysis: Analysis, week: pd.Timestamp, stores: pd.DataFrame, settings: ReputationSettings, quote_chars: int
) -> list[dict]:
    """The week's best-reviewed stores, best first. Uses this week and the week before only."""
    records = analysis.records[analysis.records["store"].notna()]
    this_week = records[records["week_start"] == week]
    if this_week.empty:
        return []
    table = _store_week(this_week).join(stores.set_index("store_id")[["avg_weekly_footfall"]], how="inner")
    last = _store_week(records[records["week_start"] == week - pd.Timedelta(weeks=1)])
    table["last_cases"] = last["cases"].reindex(table.index).fillna(0)
    chain_share = table["praise"].sum() / max(table["messages"].sum(), 1)
    table["praise_share"] = (table["praise"] + PRAISE_PRIOR_MESSAGES * chain_share) / (
        table["messages"] + PRAISE_PRIOR_MESSAGES
    )
    table["complaint_rate"] = table["cases"] / table["avg_weekly_footfall"] * 1000
    table["score"] = _score(table, settings.min_ratings)

    chain_rating = float(this_week["rating"].mean())
    chain_rate = float(table["cases"].sum() / table["avg_weekly_footfall"].sum() * 1000)
    names = stores.set_index("store_id")
    best = table.sort_values(["score", "praise"], ascending=False).head(settings.top_n)
    return [
        {
            "store_id": store,
            "name": str(names.loc[store, "store_name"]),
            "city": str(names.loc[store, "city"]),
            "region": str(names.loc[store, "region"]),
            "score": round(float(row["score"])),
            "rating": None if row["ratings"] < settings.min_ratings else round(float(row["rating"]), 1),
            "compliments": int(row["praise"]),
            "cases": int(row["cases"]),
            "reasons": _reasons(row, chain_rating, chain_rate, settings.min_ratings),
            "quote": _best_praise(this_week, store, quote_chars),
        }
        for store, row in best.iterrows()
    ]
