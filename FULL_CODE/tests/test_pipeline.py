"""End-to-end check on a small synthetic pack: the full build's flags equal the per-week detector's flags."""

import pandas as pd
import pytest

from toy_pack import MONDAYS, write_pack
from voice_of_store.data_io import load_pack
from voice_of_store.pipeline import detect_week, replay_weekly_flags


@pytest.fixture()
def pack(tmp_path):
    write_pack(tmp_path)
    return tmp_path


def test_full_build_equals_week_by_week_detector(pack, settings):
    replayed = replay_weekly_flags(load_pack(pack), settings)
    weekly = [detect_week(pack, monday + pd.Timedelta(days=3), settings) for monday in MONDAYS]
    weekly = pd.concat([w for w in weekly if not w.empty], ignore_index=True)
    pd.testing.assert_frame_equal(replayed.reset_index(drop=True), weekly, check_dtype=False)
    assert (replayed["store_id"] == "ST-AAAAA").any() and set(replayed["issue_type_id"]) == {"IT10"}


def test_detector_never_cites_feedback_after_the_as_of_week(pack, settings):
    feedback = load_pack(pack).feedback.set_index("feedback_id")
    flags = detect_week(pack, MONDAYS[8], settings)
    cited = flags["evidence_feedback_ids"].str.split(";").explode()
    assert (feedback.loc[cited, "created_at"] < MONDAYS[9]).all()
    assert (feedback.loc[cited, "created_at"] >= MONDAYS[8]).all()
