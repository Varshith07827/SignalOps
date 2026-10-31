"""The cleaner repairs a deliberately messy pack into one the engine's strict validator accepts."""

import json

import pandas as pd
import pytest

import clean
from toy_pack import write_pack
from voice_of_store.cleaning import (
    FileReport,
    canonical_channel,
    canonical_issue_id,
    canonical_store_id,
    clean_feedback,
    clean_labels,
    clean_text,
    parse_rating,
    parse_timestamp,
)
from voice_of_store.data_io import DataValidationError, load_pack, validate_feedback

COLUMNS = ["feedback_id", "channel", "created_at", "store_id", "rating", "text"]


def _messy_feedback() -> pd.DataFrame:
    rows = [
        ["FB-1", " In-App ", "2026-07-15T10:00:00", " st-aaaaa ", "4/5", "  freezer   not cold &amp; 🥶​"],
        ["FB-2", "call center", "19/07/2026 23:59", "N/A", "5 stars", "Agent: hi Customer: milk nahi hai"],
        ["FB-3", "staff_note", "2026-07-16 08:00:00+00:00", "ST-ZZZZZ", "9", "billing counter rude"],
        ["FB-1", "in_app", "2026-07-15T10:00:00", "ST-AAAAA", "4", "a second row with the same id"],
        ["FB-4", "fax", "2026-07-15T10:00:00", "", "", "unknown channel"],
        ["FB-5", "in_app", "yesterday-ish", "", "", "bad date"],
        ["", "in_app", "2026-07-15T10:00:00", "", "", "no id"],
        ["", "", "", "", "", ""],
    ]
    return pd.DataFrame(rows, columns=COLUMNS)


def test_value_helpers():
    assert canonical_channel("Call-Centre Ticket") == "call_centre_ticket"
    assert canonical_issue_id("it1") == "IT01" and canonical_issue_id("NI-03") == "NI03"
    assert canonical_store_id(" st _ab12c ") == "ST-AB12C" and canonical_store_id("null") == ""
    assert [parse_rating(v) for v in ["4.0", "3/5", "★★", "0", "", "great"]] == ["4", "3", "2", "", "", ""]
    assert parse_timestamp("05/07/2026") == pd.Timestamp("2026-07-05")  # day first
    assert parse_timestamp("2026-07-16T08:00:00Z") == pd.Timestamp("2026-07-16 13:30:00")  # to IST
    # Typos, Hinglish and emojis are signal for the classifier and survive cleaning.
    assert clean_text(" frzr  nahi chal raha 😡\n\tpls ") == "frzr nahi chal raha 😡 pls"


def test_messy_feedback_is_repaired_and_passes_validation():
    report = FileReport()
    frame = clean_feedback(_messy_feedback(), report, known_stores={"ST-AAAAA"})

    assert frame["feedback_id"].tolist() == ["FB-1", "FB-2", "FB-3"]
    assert frame["channel"].tolist() == ["in_app", "call_centre_ticket", "staff_shift_note"]
    assert frame["created_at"].tolist() == ["2026-07-15T10:00:00", "2026-07-19T23:59:00", "2026-07-16T13:30:00"]
    assert frame["store_id"].tolist() == ["ST-AAAAA", "", ""]  # ST-ZZZZZ is not a known store
    assert frame["rating"].tolist() == ["4", "5", ""]
    assert frame.loc[0, "text"] == "freezer not cold & 🥶"
    assert sum(report.dropped.values()) == 5
    validate_feedback(frame)  # raises if anything is still out of range


def test_labels_are_normalised_and_orphans_dropped():
    raw = pd.DataFrame(
        {
            "feedback_id": ["FB-1", "FB-2", "FB-3", "FB-9", "FB-1"],
            "issue_type_id": ["it10", "IT 14", "IT99", "IT01", "IT02"],
            "severity": ["High", "med", "low", "low", "low"],
            "actionable": ["yes", "0.0", "1", "1", "0"],
        }
    )
    report = FileReport()
    labels = clean_labels(raw, report, feedback_ids={"FB-1", "FB-2", "FB-3"})
    assert labels.values.tolist() == [["FB-1", "IT10", "high", "1"], ["FB-2", "IT14", "medium", "0"]]
    assert report.dropped["unknown issue_type_id"] == 1
    assert report.dropped["label for a feedback_id not in feedback"] == 1
    assert report.dropped["feedback labelled twice (kept the first)"] == 1


def _make_messy_pack(folder):
    """The toy pack with a BOM, padded header, odd casing and a duplicated, bad and unlabelled row added."""
    write_pack(folder)
    feedback = pd.read_csv(folder / "feedback.csv", dtype=str, keep_default_na=False)
    feedback["channel"] = "Staff Shift Note"
    feedback["store_id"] = " " + feedback["store_id"].str.lower()
    feedback = pd.concat([feedback, feedback.head(1)], ignore_index=True)
    feedback.loc[len(feedback)] = ["FB-BAD", "in_app", "not a date", "", "", "x"]
    feedback.columns = [f" {c.upper()} " for c in feedback.columns]
    feedback.to_csv(folder / "feedback.csv", index=False, encoding="utf-8-sig")
    stores = pd.read_csv(folder / "store_master.csv", dtype=str)
    stores["region"] = ["West", "west ", "WEST"]
    stores.to_csv(folder / "store_master.csv", index=False)


def test_clean_cli_turns_a_messy_pack_into_a_loadable_one(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "clean"
    raw.mkdir()
    _make_messy_pack(raw)
    with pytest.raises(DataValidationError):
        load_pack(raw)

    assert clean.main(["--in", str(raw), "--out", str(out)]) == 0

    pack = load_pack(out)
    assert set(pack.feedback["channel"]) == {"staff_shift_note"}
    assert pack.feedback["store_id"].str.startswith("ST-").all()
    assert set(pack.stores["region"]) == {"West"}
    report = json.loads((out / clean.REPORT_NAME).read_text(encoding="utf-8"))
    assert report["feedback.csv"]["dropped"] == {"exact duplicate row": 1, "unreadable created_at": 1}


def test_clean_cli_refuses_to_overwrite_the_raw_folder(tmp_path):
    write_pack(tmp_path)
    assert clean.main(["--in", str(tmp_path), "--out", str(tmp_path)]) == 2
