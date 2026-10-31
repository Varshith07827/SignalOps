"""The "doing well" ranking: ratings, compliments, complaints for footfall, and small stores kept in check."""

import pandas as pd

from voice_of_store.config import ReputationSettings
from voice_of_store.reputation import store_reputation
from voice_of_store.service import Analysis

WEEK = pd.Timestamp("2026-01-05")
STORES = pd.DataFrame(
    {
        "store_id": ["ST-GOOD", "ST-BAD", "ST-TINY"],
        "store_name": ["Saffron Market Good", "Saffron Market Bad", "Saffron Express Tiny"],
        "city": ["Pune", "Pune", "Pune"],
        "region": ["West", "West", "West"],
        "avg_weekly_footfall": [10000, 10000, 1000],
    }
)


def _rows(store, week, praise, complaints, ratings):
    rows = []
    for i in range(praise):
        rows.append(
            (
                store,
                week,
                "NI01",
                0,
                f"{store}-p{i}",
                "lovely store, staff very helpful today",
                ratings[i % len(ratings)],
            )
        )
    for i in range(complaints):
        rows.append((store, week, "IT01", 1, f"{store}-c{i}", "queue too long", None))
    return rows


def _analysis() -> Analysis:
    rows = (
        _rows("ST-GOOD", WEEK, praise=12, complaints=2, ratings=[5, 4, 5])
        + _rows("ST-BAD", WEEK, praise=1, complaints=20, ratings=[1, 2, 1])
        + _rows("ST-TINY", WEEK, praise=1, complaints=0, ratings=[5])
        + _rows("ST-GOOD", WEEK - pd.Timedelta(weeks=1), praise=0, complaints=6, ratings=[3])
    )
    records = pd.DataFrame(
        rows, columns=["store", "week_start", "issue_type_id", "actionable", "incident_id", "text", "rating"]
    )
    records["feedback_id"] = records["incident_id"]
    records["issue_confidence"] = 0.9
    return Analysis("test", records, pd.DataFrame(), [WEEK], ["West"])


def test_ranking_favours_ratings_compliments_and_few_complaints():
    ranking = store_reputation(_analysis(), WEEK, STORES, ReputationSettings(top_n=3, min_ratings=3), quote_chars=200)
    assert [r["store_id"] for r in ranking][0] == "ST-GOOD"
    assert ranking[-1]["store_id"] == "ST-BAD"
    good = ranking[0]
    assert good["rating"] == 4.7 and good["compliments"] == 12 and good["cases"] == 2
    assert "Complaints down from 6 to 2" in good["reasons"]
    assert good["quote"] == "lovely store, staff very helpful today"


def test_a_store_with_too_few_ratings_shows_no_average():
    ranking = store_reputation(_analysis(), WEEK, STORES, ReputationSettings(top_n=3, min_ratings=3), quote_chars=200)
    tiny = next(r for r in ranking if r["store_id"] == "ST-TINY")
    assert tiny["rating"] is None
    assert not any("Rated" in reason for reason in tiny["reasons"])


def test_a_week_with_no_feedback_ranks_nobody():
    later = WEEK + pd.Timedelta(weeks=5)
    assert store_reputation(_analysis(), later, STORES, ReputationSettings(top_n=3, min_ratings=3), 200) == []
