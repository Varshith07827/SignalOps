"""Hybrid issue classifier: keyword/phrase rules + TF-IDF logistic regression.

Pipeline for each record:
1. ``preprocessing.normalise_text`` + glossary enrichment (original text untouched).
2. Rule engine: weighted, negation-aware keyword/phrase hits per category.
3. TF-IDF (word 1-2 grams + character 3-5 grams) -> multinomial logistic regression,
   trained ONLY on the separate synthetic training corpus.
4. Hybrid probability = (1 - w) * model + w * rule distribution (when rules fire).
5. Decision: ``auto`` (>= accept threshold), ``review`` (>= review threshold) or
   ``unknown`` (below review threshold, or text with too little known vocabulary
   and no rule evidence). Unknown records get category ``unclassified``.

No Streamlit dependency: the classifier is directly testable.
Train with ``python -m src.classifier --train``.
"""
from __future__ import annotations

import argparse
import sys
import joblib
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

import config
from src import preprocessing as pp
from src.taxonomy import CATEGORIES, CATEGORY_BY_CODE, TAXONOMY_VERSION, UNCLASSIFIED

DECISION_LABELS = {
    "auto": "Auto-classified",
    "review": "Review recommended",
    "unknown": "Unclassified - review required",
}
# Rule terms whose preceding negator describes the complaint ("no allergen information").
ABSENCE_SENSITIVE = {"allergen information", "allergen info", "allergy warning", "not declared", "no stock", "no staff", "no response", "nobody to help",
                     "no one came", "without gloves", "not cooling", "not cold", "not arrived"}


class RuleEngine:
    """Weighted keyword/phrase rules from the taxonomy (multi-word phrases weigh 2)."""

    def __init__(self):
        self.weights: dict[str, dict[str, float]] = {}
        self.matchers: dict[str, pp.TermMatcher] = {}
        for c in CATEGORIES:
            terms = list(dict.fromkeys(c.keywords))
            self.weights[c.code] = {t: (2.0 if " " in t else 1.0) for t in terms}
            self.matchers[c.code] = pp.TermMatcher(terms, ABSENCE_SENSITIVE)

    def score(self, enriched: str) -> dict[str, tuple[float, list[str]]]:
        out = {}
        for code, matcher in self.matchers.items():
            hits = matcher.matches(enriched)
            if hits:
                out[code] = (sum(self.weights[code][h] for h in hits), hits)
        return out


class HybridClassifier:
    def __init__(self, settings: config.ClassifierSettings = config.CLASSIFIER):
        self.settings = settings
        self.rules = RuleEngine()
        self.word_vec = TfidfVectorizer(ngram_range=(1, settings.max_word_ngram), min_df=2, sublinear_tf=True,
                                        token_pattern=r"(?u)\b[a-z0-9_%']{2,}\b")
        self.char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=settings.char_ngram_range, min_df=3,
                                        sublinear_tf=True, max_features=60000)
        self.model = LogisticRegression(C=settings.C, max_iter=3000)
        self.classes_: np.ndarray | None = None
        self.vocab_unigrams: set[str] = set()
        self.metadata: dict = {}

    # ------------------------------------------------------------------ fit
    def fit(self, texts, labels, metadata: dict | None = None) -> "HybridClassifier":
        enriched = [pp.enrich_text(pp.normalise_text(t)) for t in texts]
        Xw = self.word_vec.fit_transform(enriched)
        Xc = self.char_vec.fit_transform(enriched)
        self.model.fit(sparse.hstack([Xw, Xc]).tocsr(), list(labels))
        self.classes_ = self.model.classes_
        self.vocab_unigrams = {t for t in self.word_vec.vocabulary_ if " " not in t}
        self.metadata = {"n_train": len(enriched), "classes": list(self.classes_),
                         "taxonomy_version": TAXONOMY_VERSION, **(metadata or {})}
        return self

    # ------------------------------------------------------------------ predict
    def _features(self, enriched: list[str]):
        return sparse.hstack([self.word_vec.transform(enriched), self.char_vec.transform(enriched)]).tocsr()

    def known_token_share(self, normalised: str) -> float:
        toks = pp.tokens(normalised)
        if not toks:
            return 0.0
        return sum(t in self.vocab_unigrams for t in toks) / len(toks)

    def predict_frame(self, texts) -> pd.DataFrame:
        """Classify an iterable of raw texts. Returns one row per text."""
        s = self.settings
        texts = list(texts)
        normalised = [pp.normalise_text(t) for t in texts]
        enriched = [pp.enrich_text(n) for n in normalised]
        ml = self.model.predict_proba(self._features(enriched))
        class_index = {c: i for i, c in enumerate(self.classes_)}
        rows = []
        for i in range(len(texts)):
            rule_scores = self.rules.score(enriched[i])
            probs = ml[i].copy()
            if rule_scores:
                rule_dist = np.zeros_like(probs)
                for code, (score, _) in rule_scores.items():
                    if code in class_index:
                        rule_dist[class_index[code]] = score
                if rule_dist.sum() > 0:
                    probs = (1 - s.rule_weight) * probs + s.rule_weight * rule_dist / rule_dist.sum()
            order = np.argsort(probs)[::-1]
            top, conf = self.classes_[order[0]], float(probs[order[0]])
            known = self.known_token_share(normalised[i])
            if known < s.min_known_token_share and not rule_scores:
                decision, reason = "unknown", "Too little recognised vocabulary and no rule evidence"
            elif conf >= s.accept_threshold:
                decision, reason = "auto", "Confidence above acceptance threshold"
            elif conf >= s.review_threshold:
                decision, reason = "review", "Moderate confidence - human review recommended"
            else:
                decision, reason = "unknown", "Confidence below review threshold"
            rows.append({
                "pred_category": top if decision != "unknown" else UNCLASSIFIED,
                "candidate_category": top,
                "confidence": round(conf, 4),
                "ml_confidence": round(float(ml[i][class_index[top]]), 4),
                "margin": round(conf - float(probs[order[1]]), 4),
                "decision": decision,
                "decision_reason": reason,
                "known_token_share": round(known, 3),
                "rule_hits": "; ".join(f"{CATEGORY_BY_CODE[c].label}: {', '.join(h)}"
                                       for c, (_, h) in sorted(rule_scores.items(), key=lambda kv: -kv[1][0])),
                "top3": "; ".join(f"{self.classes_[j]}={probs[j]:.2f}" for j in order[:3]),
            })
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ explain
    def explain(self, text: str, top_k: int = 8) -> dict:
        """Explain a single prediction: rule hits, top model features, alternatives."""
        normalised = pp.normalise_text(text)
        enriched = pp.enrich_text(normalised)
        pred = self.predict_frame([text]).iloc[0].to_dict()
        cls = pred["candidate_category"]
        ci = int(np.where(self.classes_ == cls)[0][0])
        Xw = self.word_vec.transform([enriched])
        Xc = self.char_vec.transform([enriched])
        n_word = Xw.shape[1]
        coef = self.model.coef_[ci]
        contrib_terms = []
        names_w = self.word_vec.get_feature_names_out()
        for j, v in zip(Xw.indices, Xw.data):
            contrib_terms.append((names_w[j], float(v * coef[j]), "word"))
        names_c = self.char_vec.get_feature_names_out()
        for j, v in zip(Xc.indices, Xc.data):
            contrib_terms.append((names_c[j], float(v * coef[n_word + j]), "char"))
        contrib_terms.sort(key=lambda x: -x[1])
        words = [(t, round(w, 3)) for t, w, k in contrib_terms if k == "word" and w > 0][:top_k]
        chars = [(t.strip(), round(w, 3)) for t, w, k in contrib_terms if k == "char" and w > 0][:4]
        return {
            "original_text": text,
            "normalised_text": normalised,
            "glossary_matches": [{"matched": m, "gloss": g, "language": pp.LANGUAGE_NAMES.get(lang, lang)}
                                 for m, g, lang in pp.glossary_matches(normalised)],
            "language_hint": pp.LANGUAGE_NAMES.get(pp.language_hint(normalised), "Unknown"),
            "prediction": pred,
            "top_word_features": words,
            "top_char_features": chars,
        }

    # ------------------------------------------------------------------ io
    def save(self, path=config.MODEL_PATH) -> None:
        """Persist only the fitted sklearn components and metadata (not this class)."""
        config.ensure_directories()
        joblib.dump({"word_vec": self.word_vec, "char_vec": self.char_vec, "model": self.model,
                     "metadata": self.metadata}, path)

    @staticmethod
    def load(path=config.MODEL_PATH) -> "HybridClassifier":
        state = joblib.load(path)
        clf = HybridClassifier()
        clf.word_vec, clf.char_vec, clf.model = state["word_vec"], state["char_vec"], state["model"]
        clf.metadata = state["metadata"]
        clf.classes_ = clf.model.classes_
        clf.vocab_unigrams = {t for t in clf.word_vec.vocabulary_ if " " not in t}
        return clf


def train_from_corpus(corpus: pd.DataFrame | None = None, save: bool = True) -> HybridClassifier:
    """Train on the synthetic training corpus (never on evaluation records)."""
    if corpus is None:
        if not config.TRAINING_CORPUS_PATH.exists():
            from src.data_generator import generate_training_corpus
            config.ensure_directories()
            generate_training_corpus().to_parquet(config.TRAINING_CORPUS_PATH, index=False)
        corpus = pd.read_parquet(config.TRAINING_CORPUS_PATH)
    if "true_issue_category" in corpus.columns:
        raise ValueError("Training corpus must not contain evaluation ground-truth columns.")
    clf = HybridClassifier().fit(corpus["text"], corpus["label"],
                                 metadata={"train_templates": int(corpus["template_id"].nunique())})
    if save:
        clf.save()
    return clf


def load_or_train() -> HybridClassifier:
    if config.MODEL_PATH.exists():
        return HybridClassifier.load()
    return train_from_corpus()


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # legacy Windows consoles: never crash on unusual characters
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Train / query the StorePulse classifier.")
    parser.add_argument("--train", action="store_true", help="(Re)train from the synthetic training corpus")
    parser.add_argument("--text", help="Classify a single text and print an explanation")
    args = parser.parse_args(argv)
    if args.train or not config.MODEL_PATH.exists():
        clf = train_from_corpus()
        print(f"Trained classifier on {clf.metadata['n_train']:,} synthetic training records "
              f"({len(clf.classes_)} classes). Saved to {config.MODEL_PATH}")
    else:
        clf = HybridClassifier.load()
    if args.text:
        exp = clf.explain(args.text)
        p = exp["prediction"]
        print(f"Category : {p['pred_category']} ({DECISION_LABELS[p['decision']]}, confidence {p['confidence']:.2f})")
        print(f"Top-3    : {p['top3']}")
        print(f"Rules    : {p['rule_hits'] or '-'}")
        print(f"Features : {exp['top_word_features']}")
        print(f"Language : {exp['language_hint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
