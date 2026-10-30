"""5-fold cross-validation on the labelled records.

evaluate.py scores the training labels with a model that has already seen them, so these
out-of-fold numbers are the better estimate for the hidden test set.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score
from sklearn.model_selection import StratifiedKFold

from voice_of_store.classifier import FeedbackClassifier, TrainingFrame, build_training_frame
from voice_of_store.config import Settings
from voice_of_store.data_io import PackData
from voice_of_store.text import resolve_stores

logger = logging.getLogger(__name__)

# Same weights as the official scorer.
W_ISSUE, W_SEVERITY, W_ACTIONABLE = 0.5, 0.25, 0.25


def _subset(train: TrainingFrame, rows: np.ndarray) -> TrainingFrame:
    return TrainingFrame(
        feedback=train.feedback.iloc[rows].reset_index(drop=True),
        store_known=train.store_known.iloc[rows].reset_index(drop=True),
        issue_type_id=train.issue_type_id.iloc[rows].reset_index(drop=True),
        severity=train.severity.iloc[rows].reset_index(drop=True),
        actionable=train.actionable.iloc[rows].reset_index(drop=True),
    )


def out_of_fold_predictions(data: PackData, settings: Settings) -> tuple[TrainingFrame, pd.DataFrame]:
    """Predict each labelled record with a model that never saw it."""
    feedback = data.feedback.copy()
    store_known = resolve_stores(feedback, data.stores).notna()
    train = build_training_frame(feedback, data.labels, store_known)
    folds = StratifiedKFold(settings.classifier.cv_folds, shuffle=True, random_state=settings.classifier.seed)
    parts = []
    for fit_rows, test_rows in folds.split(train.feedback, train.issue_type_id):
        model = FeedbackClassifier(settings.classifier, data.taxonomy).fit(_subset(train, fit_rows))
        held_out = _subset(train, test_rows)
        predicted = model.predict(held_out.feedback, held_out.store_known)
        parts.append(predicted.set_index(pd.Index(test_rows)))
    return train, pd.concat(parts).sort_index()


def score_predictions(train: TrainingFrame, predicted: pd.DataFrame) -> dict[str, float]:
    """Official-formula classification score plus the precision statement."""
    issue = f1_score(train.issue_type_id, predicted["issue_type_id"], average="macro")
    severity = f1_score(train.severity, predicted["severity"], average="weighted")
    actionable = f1_score(train.actionable, predicted["actionable"])
    escalated = (predicted["actionable"] == 1) & predicted["severity"].isin(["high", "critical"])
    return {
        "issue_type_macro_f1": round(float(issue), 4),
        "severity_weighted_f1": round(float(severity), 4),
        "actionable_f1": round(float(actionable), 4),
        "classification_score": round(float(W_ISSUE * issue + W_SEVERITY * severity + W_ACTIONABLE * actionable), 4),
        "precision_actionable": round(float(precision_score(train.actionable, predicted["actionable"])), 4),
        "precision_escalated_high_critical": round(float(train.actionable[escalated].mean()), 4),
        "n_marked_actionable": int((predicted["actionable"] == 1).sum()),
        "n_escalated_high_critical": int(escalated.sum()),
    }


def cross_validate(data: PackData, settings: Settings) -> dict[str, float]:
    train, predicted = out_of_fold_predictions(data, settings)
    report = score_predictions(train, predicted)
    logger.info("Cross-validated classification score %.4f", report["classification_score"])
    return report
