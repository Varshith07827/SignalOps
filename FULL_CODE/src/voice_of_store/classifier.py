"""Record-level classifier: issue type, severity and actionable flag for every feedback row.

Three linear models over the same TF-IDF features (word 1-2 grams + character 2-5 grams, which cope with the
typos, SMS spellings and code-mixed Hinglish/Tamil/Marathi), followed by the guideline rules in ``policy``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion
from sklearn.svm import LinearSVC

from voice_of_store.config import ClassifierSettings
from voice_of_store.data_io import CHANNELS, ISSUE_TYPES
from voice_of_store.policy import apply_severity_floor, can_be_actionable
from voice_of_store.text import normalise

logger = logging.getLogger(__name__)

_CHANNEL_ORDER = sorted(CHANNELS)
_ISSUE_TYPE_ORDER = list(ISSUE_TYPES)


@dataclass(frozen=True)
class TrainingFrame:
    """Labelled rows joined to their feedback, plus whether each row's store is known."""

    feedback: pd.DataFrame
    store_known: pd.Series
    issue_type_id: pd.Series
    severity: pd.Series
    actionable: pd.Series


def _one_hot(values: pd.Series, categories: list[str]) -> sp.csr_matrix:
    index = {c: i for i, c in enumerate(categories)}
    cols = values.map(index).fillna(-1).astype(int).to_numpy()
    rows = np.arange(len(values))
    keep = cols >= 0
    data = np.ones(keep.sum())
    return sp.csr_matrix((data, (rows[keep], cols[keep])), shape=(len(values), len(categories)))


def _context_features(feedback: pd.DataFrame, issue_types: pd.Series, store_known: pd.Series) -> sp.csr_matrix:
    """Non-text signals for severity/actionable: channel, issue type, routability, specificity cues."""
    text = feedback["text"]
    numeric = np.column_stack(
        [
            store_known.to_numpy(dtype=float),
            text.str.contains(r"\d", regex=True).to_numpy(dtype=float),
            np.log1p(text.str.len().to_numpy(dtype=float)) / 6.0,
        ]
    )
    return sp.hstack(
        [
            _one_hot(feedback["channel"].reset_index(drop=True), _CHANNEL_ORDER),
            _one_hot(issue_types.reset_index(drop=True), _ISSUE_TYPE_ORDER),
            sp.csr_matrix(numeric),
        ]
    ).tocsr()


class FeedbackClassifier:
    """Trained on the labelled records, then used to label any feedback rows."""

    def __init__(self, settings: ClassifierSettings, taxonomy: pd.DataFrame) -> None:
        self.settings = settings
        self.taxonomy = taxonomy
        self.vectorizer = FeatureUnion(
            [
                ("word", TfidfVectorizer(ngram_range=(1, settings.word_ngram_max), sublinear_tf=True)),
                (
                    "char",
                    TfidfVectorizer(
                        analyzer="char_wb",
                        ngram_range=(settings.char_ngram_min, settings.char_ngram_max),
                        min_df=settings.char_min_df,
                        sublinear_tf=True,
                    ),
                ),
            ]
        )
        self.issue_model = LinearSVC(C=settings.issue_c, class_weight="balanced", random_state=settings.seed)
        self.severity_model = LogisticRegression(
            C=settings.severity_c, class_weight="balanced", max_iter=3000, random_state=settings.seed
        )
        self.actionable_model = LogisticRegression(C=settings.actionable_c, max_iter=3000, random_state=settings.seed)
        self.known_texts: dict[str, str] = {}

    def fit(self, train: TrainingFrame) -> FeedbackClassifier:
        texts = train.feedback["text"].map(normalise)
        text_matrix = self.vectorizer.fit_transform(texts)
        self.issue_model.fit(text_matrix, train.issue_type_id)
        # Train on the true issue type. At prediction time these models get the predicted one.
        full = sp.hstack(
            [text_matrix, _context_features(train.feedback, train.issue_type_id, train.store_known)]
        ).tocsr()
        self.severity_model.fit(full, train.severity)
        self.actionable_model.fit(full, train.actionable)
        # Identical texts always share a label in this dataset, so reuse it for exact matches.
        self.known_texts = dict(zip(texts, train.issue_type_id, strict=True))
        logger.info("Classifier trained on %d labelled records", len(texts))
        return self

    def predict(self, feedback: pd.DataFrame, store_known: pd.Series) -> pd.DataFrame:
        """Return issue_type_id, severity, actionable and issue_confidence for each row of ``feedback``."""
        texts = feedback["text"].map(normalise)
        text_matrix = self.vectorizer.transform(texts)
        margins = self.issue_model.decision_function(text_matrix)
        issue_types = pd.Series(self.issue_model.classes_[margins.argmax(axis=1)], index=feedback.index)
        exact = texts.map(self.known_texts)
        issue_types = exact.fillna(issue_types)

        full = sp.hstack([text_matrix, _context_features(feedback, issue_types, store_known)]).tocsr()
        severity = pd.Series(self.severity_model.predict(full), index=feedback.index)
        severity = apply_severity_floor(severity, issue_types, self.taxonomy)
        actionable = pd.Series(self.actionable_model.predict(full), index=feedback.index).astype(int)
        actionable = actionable.where(can_be_actionable(issue_types, store_known), 0)

        return pd.DataFrame(
            {
                "issue_type_id": issue_types,
                "severity": severity,
                "actionable": actionable,
                "issue_confidence": _margin_confidence(margins),
            },
            index=feedback.index,
        )


def _margin_confidence(margins: np.ndarray) -> np.ndarray:
    """Map the gap between the best and runner-up SVM scores to (0, 1); a wide gap means a clear call."""
    top_two = np.sort(margins, axis=1)[:, -2:]
    gap = top_two[:, 1] - top_two[:, 0]
    return np.round(1.0 / (1.0 + np.exp(-4.0 * gap)), 3)


def build_training_frame(feedback: pd.DataFrame, labels: pd.DataFrame, store_known: pd.Series) -> TrainingFrame:
    """Join labels to their feedback rows (inner join: labels without feedback are ignored)."""
    position = pd.Series(np.arange(len(feedback)), index=feedback["feedback_id"])
    labels = labels[labels["feedback_id"].isin(position.index)]
    rows = position.loc[labels["feedback_id"]].to_numpy()
    return TrainingFrame(
        feedback=feedback.iloc[rows].reset_index(drop=True),
        store_known=store_known.iloc[rows].reset_index(drop=True),
        issue_type_id=labels["issue_type_id"].reset_index(drop=True),
        severity=labels["severity"].reset_index(drop=True),
        actionable=labels["actionable"].reset_index(drop=True),
    )
