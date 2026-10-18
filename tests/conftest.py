"""Shared, session-scoped fixtures.

Unit tests use tiny hand-written fixtures. Integration tests share ONE reduced
synthetic dataset (12k records, same planted scenarios) and a classifier
trained on a reduced training corpus, so the 40k dataset is never regenerated
during the test run.
"""
from __future__ import annotations

import pandas as pd
import pytest

import config
from src import data_generator
from src.classifier import HybridClassifier
from src.pipeline import analyse, process_feedback

SMALL = config.GeneratorSettings(n_records=12_000, training_per_class=120)


@pytest.fixture(scope="session")
def small_settings():
    return SMALL


@pytest.fixture(scope="session")
def small_dataset():
    return data_generator.generate_dataset(SMALL)


@pytest.fixture(scope="session")
def training_corpus():
    return data_generator.generate_training_corpus(SMALL)


@pytest.fixture(scope="session")
def classifier(training_corpus):
    return HybridClassifier().fit(training_corpus["text"], training_corpus["label"])


@pytest.fixture(scope="session")
def pipeline_output(small_dataset, classifier):
    df, stores, manifest = small_dataset
    processed = process_feedback(df, stores, classifier)
    res = analyse(processed, stores)
    gt = df[["feedback_id"] + config.GROUND_TRUTH_COLUMNS]
    joined = processed.merge(gt, on="feedback_id")
    return {"processed": processed, "joined": joined, "stores": stores, "manifest": manifest, **res}


def make_records(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal processed-like frame for dedup / detection unit tests."""
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed")
    return df
