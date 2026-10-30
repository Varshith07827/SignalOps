"""Text normalisation, store attribution from text, and a light language detector."""

from __future__ import annotations

import re

import pandas as pd

# The opening "Agent: <greeting> Customer:" turn of a call transcript says nothing about the issue.
_AGENT_GREETING = re.compile(r"agent:.*?customer:", re.IGNORECASE | re.DOTALL)
_WHITESPACE = re.compile(r"\s+")


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# Function words that mark each language variety. Texts are Latin script, so script cannot help.
_LANGUAGE_MARKERS = {
    "hinglish": _words(
        "hai hain nahi nhi kya bahut bht mein aur ke ki ko tha thi wala kar bhi raha gaye liya hoon kyun abhi yahan koi"
    ),
    "tamil": _words(
        "illa irukku romba enna aana pannunga vandhu inga nu dhaan aagudhu kedaikkala sollunga unga naan la ku "
        "aayiduchu panna theriyanum"
    ),
    "marathi": _words(
        "aahe nahi hota hoti ani pan kahi mala madhe zala zali khup aapla kara sanga ahe chya la kay milali"
    ),
}
_TOKEN = re.compile(r"[a-z]+")


def normalise(text: str) -> str:
    """Lower-case, strip the call-centre greeting turn and squeeze whitespace."""
    lowered = _AGENT_GREETING.sub(" ", str(text).lower(), count=1)
    return _WHITESPACE.sub(" ", lowered).strip()


def detect_language(text: str) -> str:
    """Best-guess language variety: english, hinglish, tamil or marathi (marker-word vote)."""
    tokens = _TOKEN.findall(str(text).lower())
    if not tokens:
        return "english"
    scores = {lang: sum(t in markers for t in tokens) for lang, markers in _LANGUAGE_MARKERS.items()}
    best = max(scores, key=lambda lang: scores[lang])
    # A couple of shared words ("la", "nahi") is not enough to call a text non-English.
    return best if scores[best] >= 2 and scores[best] / len(tokens) >= 0.08 else "english"


def resolve_stores(feedback: pd.DataFrame, stores: pd.DataFrame) -> pd.Series:
    """Store each record is about: its ``store_id``, else the single store whose locality the text names.

    Mirrors the evaluator's evidence rule (b). A text naming two localities stays unresolved rather than guessed.
    """
    patterns = [(row.store_id, re.compile(rf"\b{re.escape(row.locality)}\b")) for row in stores.itertuples(index=False)]

    def from_text(text: str) -> str | None:
        lowered = text.lower()
        hits = [store_id for store_id, pattern in patterns if pattern.search(lowered)]
        return hits[0] if len(hits) == 1 else None

    resolved = feedback["store_id"].copy()
    missing = resolved.isna()
    resolved[missing] = feedback.loc[missing, "text"].map(from_text)
    return resolved
