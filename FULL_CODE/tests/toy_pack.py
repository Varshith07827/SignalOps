"""A tiny synthetic problem pack (3 stores, 10 weeks) with one planted freezer spike, plus demo accounts."""

import pandas as pd

from voice_of_store.accounts import save_user
from voice_of_store.database import apply_schema, session

MONDAYS = list(pd.date_range("2026-01-05", periods=10, freq="7D"))
STORES = {
    "ST-AAAAA": "Saffron Hyper Kothrud",
    "ST-BBBBB": "Saffron Market Vashi",
    "ST-CCCCC": "Saffron Express Aundh",
}
TEXTS = {
    "IT10": "freezer not cold, ice cream melted {k}",
    "IT14": "milk out of stock again shelf empty {k}",
    "NI01": "great service thank you {k}",
}


def write_pack(folder):
    feedback, labels = [], []

    def add(store, issue_type, monday, k, label):
        fid = f"FB-{len(feedback):06d}"
        stamp = monday + pd.Timedelta(hours=9 + k)
        feedback.append(
            [
                fid,
                "staff_shift_note",
                stamp.strftime("%Y-%m-%dT%H:%M:%S"),
                store,
                "",
                TEXTS[issue_type].format(k=k),
            ]
        )
        if label:
            labels.append(
                [fid, issue_type, "high" if issue_type == "IT10" else "low", 1 if issue_type != "NI01" else 0]
            )

    for w, monday in enumerate(MONDAYS):
        for store in STORES:
            for k in range(6):
                add(store, "NI01", monday, k, label=w < 4 and k == 0)
            for k in range(2):
                add(store, "IT14", monday, k, label=w < 4 and k == 0)
            if w in (1, 3) and store != "ST-AAAAA":
                add(store, "IT10", monday, 7, label=True)
    for k in range(4):
        add("ST-AAAAA", "IT10", MONDAYS[8], 10 + k, label=False)

    pd.DataFrame(feedback, columns=["feedback_id", "channel", "created_at", "store_id", "rating", "text"]).to_csv(
        folder / "feedback.csv", index=False
    )
    pd.DataFrame(labels, columns=["feedback_id", "issue_type_id", "severity", "actionable"]).to_csv(
        folder / "feedback_labels_train.csv", index=False
    )
    pd.DataFrame(
        {
            "store_id": list(STORES),
            "store_name": list(STORES.values()),
            "city": "Pune",
            "region": "West",
            "format": "Saffron Market",
            "avg_weekly_footfall": 1000,
        }
    ).to_csv(folder / "store_master.csv", index=False)
    floors = {f"IT{i:02d}": ("high" if i in (4, 6, 8, 10, 16, 17, 18) else "low") for i in range(1, 31)}
    taxonomy = [[t, t, "Store Ops", f, "1"] for t, f in floors.items()]
    taxonomy += [[t, t, "None (not actionable)", "low", "0"] for t in ("NI01", "NI02", "NI03")]
    pd.DataFrame(
        taxonomy,
        columns=[
            "issue_type_id",
            "issue_type",
            "owner_function",
            "policy_severity_floor",
            "is_actionable_category",
        ],
    ).to_csv(folder / "issue_taxonomy.csv", index=False)
    pd.DataFrame(
        {
            "week_index": range(1, len(MONDAYS) + 1),
            "week_start": [m.date() for m in MONDAYS],
            "week_end": [(m + pd.Timedelta(days=6)).date() for m in MONDAYS],
        }
    ).to_csv(folder / "week_calendar.csv", index=False)


HEADERS = {"X-Requested-With": "voice-of-store"}
PASSWORDS = {"head-office": "admin-pass-1", "kothrud": "store-pass-1", "vashi": "store-pass-2"}


def add_accounts(database_path):
    """Head office plus managers for Kothrud (ST-AAAAA) and Vashi (ST-BBBBB)."""
    apply_schema(database_path)
    with session(database_path) as connection:
        save_user(connection, "head-office", "Head office", PASSWORDS["head-office"], "admin")
        save_user(connection, "kothrud", "Kothrud manager", PASSWORDS["kothrud"], "store", "ST-AAAAA")
        save_user(connection, "vashi", "Vashi manager", PASSWORDS["vashi"], "store", "ST-BBBBB")


def sign_in(client, username):
    response = client.post("/api/login", json={"username": username, "password": PASSWORDS[username]}, headers=HEADERS)
    assert response.status_code == 200, response.text
    client.headers.update(HEADERS)
    return client
