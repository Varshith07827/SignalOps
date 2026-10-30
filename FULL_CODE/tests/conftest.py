"""Shared fixtures. Tests never read the pack's data folder, so they run on a fresh clone."""

from __future__ import annotations

import pandas as pd
import pytest

from voice_of_store.config import Settings, load_settings

HIGH_FLOOR = {"IT04", "IT06", "IT08", "IT10", "IT16", "IT17", "IT18"}
OWNERS = {
    "IT01": "Store Ops",
    "IT10": "Store Ops",
    "IT14": "Supply Chain",
    "IT18": "Merchandising",
    "IT26": "Digital",
}


@pytest.fixture(scope="session")
def settings() -> Settings:
    return load_settings()


@pytest.fixture(scope="session")
def taxonomy() -> pd.DataFrame:
    rows = []
    for i in range(1, 31):
        type_id = f"IT{i:02d}"
        floor = "high" if type_id in HIGH_FLOOR else "medium" if type_id == "IT27" else "low"
        rows.append((type_id, f"Issue {i}", OWNERS.get(type_id, "Store Ops"), floor, "1"))
    for type_id in ("NI01", "NI02", "NI03"):
        rows.append((type_id, f"Non-issue {type_id}", "None (not actionable)", "low", "0"))
    columns = [
        "issue_type_id",
        "issue_type",
        "owner_function",
        "policy_severity_floor",
        "is_actionable_category",
    ]
    return pd.DataFrame(rows, columns=columns).set_index("issue_type_id")


@pytest.fixture()
def stores() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "store_id": ["ST-AAAAA", "ST-BBBBB", "ST-CCCCC"],
            "store_name": ["Saffron Hyper Kothrud", "Saffron Express Vashi", "Saffron Market MG Road"],
            "region": ["West", "West", "South"],
            "locality": ["kothrud", "vashi", "mg road"],
        }
    )
