import numpy as np
import pandas as pd
import pytest

import config
from src import preprocessing as pp
from src.pipeline import process_feedback, strip_ground_truth
from src.taxonomy import UNCLASSIFIED


@pytest.mark.parametrize("text,expected", [
    ("The dairy chiller was not cold at all, milk felt warm", "refrigeration_failure"),
    ("freezer band pada hai, ice cream pighal gaya 🥶", "refrigeration_failure"),
    ("UPI payment failed at counter 3 but money was debited", "payment_failure"),
    ("paisa kat gaya par bill nahi bana, card machine kaam nahi kar rahi", "payment_failure"),
    ("Saw a rat running across the grocery aisle!", "pest_sighting"),
    ("cashier ne badtameezi ki, bahut rude tha", "staff_misconduct"),
    ("The label says nut-free but the ingredients mention peanuts", "allergen_labelling"),
    ("Only one billing counter open, queue was 30 minutes", "queue_management"),
    ("app keeps crashing when I open the cart", "app_failure"),
    ("Very clean store, no hygiene issues at all.", "no_issue"),
])
def test_known_phrases(classifier, text, expected):
    pred = classifier.predict_frame([text]).iloc[0]
    assert pred["candidate_category"] == expected
    assert pred["decision"] in ("auto", "review")


@pytest.mark.parametrize("text", [
    "Do you sell gift cards for corporate events?",
    "asdf qwerty zxcv",
    "ivide puthiya shakha thurakkumo",  # Malayalam (transliterated) - not supported
    "",
])
def test_unknown_inputs_are_not_forced_into_a_category(classifier, text):
    pred = classifier.predict_frame([text]).iloc[0]
    assert pred["decision"] == "unknown"
    assert pred["pred_category"] == UNCLASSIFIED


def test_out_of_taxonomy_mostly_abstained(pipeline_output):
    j = pipeline_output["joined"]
    other = j[j["true_issue_category"] == "other"]
    assert len(other) > 50
    assert (other["decision"] == "auto").mean() < 0.10


def test_normalisation_preserves_negation_and_original():
    original = "Fridge NOT cooling!!! pls chk 😡"
    norm = pp.normalise_text(original)
    assert "not cooling" in norm and "please" in norm and "emoji_angry" in norm
    assert original == "Fridge NOT cooling!!! pls chk 😡"
    found, negated = pp.find_term("no hygiene issues here", "hygiene")
    assert found and negated
    assert pp.matched_terms("no allergen information on pack", ["allergen information"],
                            absence_sensitive={"allergen information"}) == ["allergen information"]


def test_glossary_and_language_hint():
    assert "not cold" in pp.enrich_text(pp.normalise_text("chiller thanda nahi hai"))
    assert pp.language_hint(pp.normalise_text("store chala dirty ga undi")) == "te"
    assert pp.language_hint(pp.normalise_text("the fridge is broken")) == "en"


def test_explanation_contains_evidence(classifier):
    exp = classifier.explain("Payment machine at counter 2 not working, card declined")
    assert exp["prediction"]["candidate_category"] == "payment_failure"
    assert exp["top_word_features"], "expected contributing terms"
    assert "Payment failure" in exp["prediction"]["rule_hits"]


def test_strip_ground_truth_removes_labels(small_dataset):
    df, _, _ = small_dataset
    clean = strip_ground_truth(df)
    assert list(clean.columns) == config.INFERENCE_COLUMNS
    assert not set(clean.columns) & set(config.GROUND_TRUTH_COLUMNS)


def test_ground_truth_cannot_influence_predictions(small_dataset, classifier):
    """Data-leakage guard: scrambling every ground-truth column leaves outputs unchanged."""
    df, stores, _ = small_dataset
    sample = df.sample(400, random_state=0).sort_values("timestamp")
    scrambled = sample.copy()
    rng = np.random.default_rng(0)
    for col in config.GROUND_TRUTH_COLUMNS:
        scrambled[col] = rng.permutation(scrambled[col].to_numpy())
    a = process_feedback(sample, stores, classifier)
    b = process_feedback(scrambled, stores, classifier)
    cols = ["feedback_id", "pred_category", "confidence", "policy_severity", "cluster_id"]
    pd.testing.assert_frame_equal(a[cols], b[cols])
