import pandas as pd

from voice_of_store.classifier import FeedbackClassifier, build_training_frame

TEMPLATES = {
    "IT10": ("freezer not cold, ice cream melted at {s}", "high", 1),
    "IT18": ("label says no peanut but it has peanut, allergic reaction {s}", "critical", 1),
    "IT26": ("app crashed at login again {s}", "low", 1),
    "NI01": ("great service, thank you so much {s}", "low", 0),
}


def _toy_data(n_per_class: int = 12):
    rows, labels = [], []
    for issue_type, (template, severity, actionable) in TEMPLATES.items():
        for k in range(n_per_class):
            fid = f"FB-{issue_type}-{k}"
            rows.append({"feedback_id": fid, "channel": "in_app", "text": template.format(s=f"visit {k}")})
            labels.append(
                {
                    "feedback_id": fid,
                    "issue_type_id": issue_type,
                    "severity": severity,
                    "actionable": actionable,
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(labels)


def _fitted(taxonomy, settings):
    feedback, labels = _toy_data()
    store_known = pd.Series(True, index=feedback.index)
    train = build_training_frame(feedback, labels, store_known)
    return FeedbackClassifier(settings.classifier, taxonomy).fit(train)


def test_predicts_issue_type_and_applies_policy_rules(taxonomy, settings):
    model = _fitted(taxonomy, settings)
    unseen = pd.DataFrame(
        {
            "channel": ["in_app"] * 4,
            "text": [
                "the freezer is not cold",
                "app crashed during login",
                "thank you, great service",
                "freezer not cold, ice cream melted",
            ],
        }
    )
    store_known = pd.Series([True, False, True, False])
    result = model.predict(unseen, store_known)
    assert result["issue_type_id"].tolist() == ["IT10", "IT26", "NI01", "IT10"]
    assert result.loc[0, "severity"] in {"high", "critical"}  # IT10 policy floor is high
    assert result.loc[2, "actionable"] == 0  # praise is never actionable
    assert result.loc[3, "actionable"] == 0  # store unknown and not an online/app issue
    assert result["issue_confidence"].between(0, 1).all()


def test_exact_training_text_reuses_its_label(taxonomy, settings):
    model = _fitted(taxonomy, settings)
    text = TEMPLATES["IT18"][0].format(s="visit 3")
    result = model.predict(pd.DataFrame({"channel": ["in_app"], "text": [text]}), pd.Series([True]))
    assert result.loc[0, "issue_type_id"] == "IT18"
    assert result.loc[0, "severity"] == "critical"


def test_training_frame_ignores_labels_without_feedback():
    feedback, labels = _toy_data(2)
    labels = pd.concat(
        [
            labels,
            pd.DataFrame([{"feedback_id": "FB-FUTURE", "issue_type_id": "IT10", "severity": "high", "actionable": 1}]),
        ]
    )
    train = build_training_frame(feedback, labels, pd.Series(True, index=feedback.index))
    assert len(train.feedback) == len(feedback)
    assert "FB-FUTURE" not in set(train.feedback["feedback_id"])
