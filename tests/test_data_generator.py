import pandas as pd

import config
from src import data_generator as dg
from src.taxonomy import CATEGORIES, OUT_OF_TAXONOMY


def test_schema_valid_and_size(small_dataset, small_settings):
    df, stores, manifest = small_dataset
    assert len(df) == small_settings.n_records
    assert dg.validate_dataset(df, stores) == []
    for col in config.INFERENCE_COLUMNS + config.GROUND_TRUTH_COLUMNS:
        assert col in df.columns
    assert set(df.channel) == set(config.CHANNELS)


def test_validation_catches_problems(small_dataset):
    df, stores, _ = small_dataset
    bad = df.head(50).copy()
    bad.loc[bad.index[0], "channel"] = "fax"
    bad.loc[bad.index[1], "feedback_id"] = bad.loc[bad.index[2], "feedback_id"]
    problems = dg.validate_dataset(bad, stores)
    assert any("channel" in p for p in problems)
    assert any("duplicate feedback_id" in p for p in problems)


def test_reproducible_with_same_seed():
    s = config.GeneratorSettings(n_records=1500)
    a, _, ma = dg.generate_dataset(s)
    b, _, mb = dg.generate_dataset(s)
    pd.testing.assert_frame_equal(a, b)
    assert ma["scenarios"] == mb["scenarios"]


def test_different_seed_changes_data():
    a, _, _ = dg.generate_dataset(config.GeneratorSettings(n_records=1500, seed=1))
    b, _, _ = dg.generate_dataset(config.GeneratorSettings(n_records=1500, seed=2))
    assert not a["original_text"].equals(b["original_text"])


def test_store_master_has_regions_and_sizes(small_dataset):
    _, stores, _ = small_dataset
    assert stores["region"].nunique() == 5
    assert set(stores["format"]) == {"Express", "Neighbourhood", "Superstore", "Hypermarket"}
    assert stores["footfall_index"].max() > 3 * stores["footfall_index"].min()


def test_category_count_and_language_mix(small_dataset):
    df, _, _ = small_dataset
    assert 28 <= len([c for c in CATEGORIES if c.actionable]) <= 32
    langs = set(df["true_language"])
    assert {"en", "hi-Latn"} <= langs
    assert len(langs - {"en", "hi-Latn"}) >= 3  # small controlled regional sample
    assert (df["true_issue_category"] == OUT_OF_TAXONOMY).any()
    assert df["original_text"].str.contains("[\U0001F300-\U0001FAFF]", regex=True).any()  # emojis


def test_planted_scenarios_documented(small_dataset):
    df, stores, manifest = small_dataset
    sc = manifest["scenarios"]
    assert set(sc) == {"A", "B", "C"}
    assert sc["B"]["n_reports"] == 1
    for key in ("A", "C"):
        rows = df[df["planted_scenario"] == key]
        assert len(rows) == sc[key]["n_reports"] >= 15
        assert rows["channel"].nunique() >= 3
        assert (rows["store_id"] == sc[key]["store_id"]).all()
        assert rows["is_planted_incident"].all()
    assert "onset" in manifest["onset_definition"].lower()
    assert manifest["negative_controls"]["N1"]["store_id"] in set(stores["store_id"])


def test_training_corpus_excludes_holdout_and_out_of_taxonomy(training_corpus):
    holdout = {t.template_id for t in dg.build_template_catalogue() if t.split == "holdout"}
    assert holdout, "expected some hold-out templates"
    assert not set(training_corpus["template_id"]) & holdout
    assert OUT_OF_TAXONOMY not in set(training_corpus["label"])
    # only text + label (+ template id used for this split check) - no evaluation ground truth
    assert not set(training_corpus.columns) & (set(config.GROUND_TRUTH_COLUMNS) - {"template_id"})


def test_duplicates_exist_in_ground_truth(small_dataset):
    df, _, _ = small_dataset
    sizes = df["incident_id"].value_counts()
    assert (sizes > 1).sum() > 100
