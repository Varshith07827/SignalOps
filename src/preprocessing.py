"""Text normalisation for noisy, code-mixed retail feedback.

Design principles
-----------------
* The original text is never modified; normalisation produces a separate field.
* Negation words (``not``, ``no``, ``nahi`` ...) and safety terminology are kept,
  because they change both the category and the severity of a report.
* Hinglish and a handful of transliterated regional phrases are mapped to
  English *glosses* through an explicit, documented glossary. Glosses are
  appended to the text rather than replacing it. Only phrases listed in
  ``GLOSSARY`` are supported; this is not general multilingual understanding.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# --------------------------------------------------------------------------- #
# Emoji handling: map to explicit tokens so sentiment cues survive tokenising
# --------------------------------------------------------------------------- #
EMOJI_TOKENS = {
    "😡": "emoji_angry", "😤": "emoji_angry", "😠": "emoji_angry", "🤬": "emoji_angry",
    "👎": "emoji_negative", "😞": "emoji_negative", "🙄": "emoji_negative",
    "🤢": "emoji_sick", "🤮": "emoji_sick",
    "🥶": "emoji_cold", "❄️": "emoji_cold", "❄": "emoji_cold",
    "💸": "emoji_money",
    "🐀": "emoji_rat rat", "🪳": "emoji_cockroach cockroach",
    "👍": "emoji_positive", "😊": "emoji_positive", "🙏": "emoji_positive", "❤️": "emoji_positive",
    "❤": "emoji_positive", "👌": "emoji_positive",
}

# --------------------------------------------------------------------------- #
# Abbreviations and common shorthand (expanded in the normalised text)
# --------------------------------------------------------------------------- #
ABBREVIATION_MAP = {
    "pls": "please", "plz": "please", "u": "you", "ur": "your", "r": "are", "bcoz": "because",
    "coz": "because", "mrng": "morning", "ppl": "people", "vry": "very", "temp": "temperature",
    "mins": "minutes", "hrs": "hours", "pymt": "payment", "amt": "amount", "thx": "thanks",
    "cust": "customer", "custs": "customers", "wid": "with", "2day": "today", "nt": "not",
    "wat": "what", "txn": "transaction", "txns": "transactions", "chk": "check", "mgr": "manager",
    "deg": "degrees", "frige": "fridge", "fridg": "fridge", "freezr": "freezer", "oos": "out of stock",
    "dc": "distribution centre", "qa": "quality", "sm": "store manager", "b4": "before",
}

NEGATORS = {"no", "not", "never", "without", "nothing", "none", "nahi", "nhi", "nai", "illa", "ledu",
            "isn't", "wasn't", "didn't", "doesn't", "don't", "can't", "couldn't", "won't"}

# --------------------------------------------------------------------------- #
# Controlled glossary: (regex, English gloss, language tag)
# Language tags: hi-Latn = Hinglish; ta/te/mr/bn/kn = transliterated regional.
# --------------------------------------------------------------------------- #
GLOSSARY: list[tuple[str, str, str]] = [
    # Hinglish
    (r"thanda nahi", "not cold", "hi-Latn"),
    (r"garam", "warm hot", "hi-Latn"),
    (r"pighal", "melted", "hi-Latn"),
    (r"kharab", "broken bad", "hi-Latn"),
    (r"band (?:pada|hai|tha)", "not working closed", "hi-Latn"),
    (r"ganda|gandagi", "dirty", "hi-Latn"),
    (r"kachra", "garbage", "hi-Latn"),
    (r"badbu", "bad smell", "hi-Latn"),
    (r"safai", "cleaning", "hi-Latn"),
    (r"chuha|chuhe", "rat", "hi-Latn"),
    (r"makkhi(?:yan)?", "flies", "hi-Latn"),
    (r"badtameezi", "rude misbehaviour", "hi-Latn"),
    (r"gaali", "abusive language", "hi-Latn"),
    (r"chor bola", "accused me of stealing", "hi-Latn"),
    (r"paisa kat gaya|paise? kat gaye|cut gaye|paisa kat", "money deducted", "hi-Latn"),
    (r"bill galat", "wrong bill", "hi-Latn"),
    (r"do baar", "twice", "hi-Latn"),
    (r"zyada le liya", "overcharged", "hi-Latn"),
    (r"line (?:bahut )?lambi|lambi line", "long queue", "hi-Latn"),
    (r"khali", "empty", "hi-Latn"),
    (r"stock khatam|khatam", "out of stock", "hi-Latn"),
    (r"beemar", "sick", "hi-Latn"),
    (r"ulti", "vomiting", "hi-Latn"),
    (r"expiry date nikal|date nikla", "expired", "hi-Latn"),
    (r"nahi aaya", "not arrived", "hi-Latn"),
    (r"gir gay[ae]|gir gaya", "fell", "hi-Latn"),
    (r"chot", "injury", "hi-Latn"),
    (r"geela", "wet", "hi-Latn"),
    (r"basi", "stale", "hi-Latn"),
    (r"sade|sada", "rotten", "hi-Latn"),
    (r"phata", "torn", "hi-Latn"),
    (r"pichka", "crushed", "hi-Latn"),
    (r"wapas", "return", "hi-Latn"),
    (r"garmi", "hot", "hi-Latn"),
    (r"ghutan", "stuffy", "hi-Latn"),
    (r"likha nahi|info hi nahi", "not declared", "hi-Latn"),
    (r"khatarnak", "dangerous", "hi-Latn"),
    (r"tukda", "piece", "hi-Latn"),
    (r"accha|achha|badhiya", "good", "hi-Latn"),
    (r"saman", "items", "hi-Latn"),
    (r"rakhte hi nahi|milta hi nahi", "does not carry", "hi-Latn"),
    (r"(?:nahi|nhi|nai)\b", "not", "hi-Latn"),
    # Tamil (transliterated)
    (r"cooling illa", "not cooling", "ta"),
    (r"sudaa", "hot", "ta"),
    (r"romba kootam|kootam", "crowd long queue", "ta"),
    (r"\beli\b", "rat", "ta"),
    (r"panam cut", "money deducted", "ta"),
    (r"romba nalla|nalla", "good", "ta"),
    (r"romba", "very", "ta"),
    (r"vikkiringa", "selling", "ta"),
    (r"pesinanga", "spoke", "ta"),
    # Telugu (transliterated)
    (r"pani cheyyatledu", "not working", "te"),
    (r"vedi", "hot", "te"),
    (r"dabbulu cut", "money deducted", "te"),
    (r"bagundi", "good", "te"),
    (r"chala", "very", "te"),
    (r"matladaru", "spoke", "te"),
    # Marathi (transliterated)
    (r"band aahe", "not working", "mr"),
    (r"ghaan", "dirty", "mr"),
    (r"khup", "very", "mr"),
    (r"rikama", "empty", "mr"),
    # Bengali (transliterated)
    (r"nongra", "dirty", "bn"),
    (r"khub bhalo", "very good", "bn"),
    (r"gondho", "smell", "bn"),
    # Kannada (transliterated)
    (r"tumba", "very", "kn"),
    (r"ketta", "bad", "kn"),
]
LANGUAGE_NAMES = {
    "hi-Latn": "Hinglish (Latin script)", "ta": "Tamil (transliterated)", "te": "Telugu (transliterated)",
    "mr": "Marathi (transliterated)", "bn": "Bengali (transliterated)", "kn": "Kannada (transliterated)",
    "en": "English",
}

_COMPILED_GLOSSARY = [(re.compile(rf"\b(?:{pat})"), gloss, lang) for pat, gloss, lang in GLOSSARY]

# --------------------------------------------------------------------------- #
# Generic retail entity lexicon for deduplication (products, places, payment)
# --------------------------------------------------------------------------- #
ENTITY_LEXICON = [
    # products
    "milk", "curd", "paneer", "butter", "cheese", "ice cream", "frozen peas", "yogurt", "chicken", "fish",
    "cookies", "chocolate", "granola", "bread", "sauce", "namkeen", "protein bar", "biscuit", "muffin",
    "biryani", "sandwich", "salad", "cake", "samosa", "tomato", "banana", "apple", "onion", "potato",
    "mango", "spinach", "rice", "atta", "egg", "sugar", "oil", "dal", "diaper", "honey", "oat milk",
    "detergent", "shampoo", "coffee", "ghee", "juice", "ketchup", "flour", "kettle", "shoes", "mixer",
    # locations / fixtures
    "dairy", "chiller", "freezer", "cold section", "meat counter", "frozen food", "bakery", "snacks",
    "aisle 4", "produce", "billing", "counter 2", "counter 3", "self checkout", "entrance", "washroom",
    "staircase", "parking", "fish section", "vegetable section", "storage area", "first floor",
    "escalator", "lift", "weighing", "express", "hot food", "deli",
    # payment / digital
    "upi", "card", "qr", "pos", "otp", "cart", "checkout", "login", "wallet", "delivery", "slot",
]
_ENTITY_PATTERNS = [(e, re.compile(rf"\b{re.escape(e)}s?\b")) for e in ENTITY_LEXICON]

_WORD_RE = re.compile(r"[a-z0-9%']+")


def normalise_text(text: str | None) -> str:
    """Return a cleaned, lower-cased version of ``text`` (original is untouched)."""
    if not isinstance(text, str) or not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    for emoji, token in EMOJI_TOKENS.items():
        if emoji in s:
            s = s.replace(emoji, f" {token} ")
    s = s.lower()
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"(.)\1{2,}", r"\1\1", s)  # sooo -> soo, !!! -> !!
    s = s.replace("₹", " rs ")
    s = re.sub(r"[^a-z0-9%'_\-\s]", " ", s)
    s = re.sub(r"(?<![a-z])-|-(?![a-z])", " ", s)
    tokens = [ABBREVIATION_MAP.get(tok, tok) for tok in s.split()]
    return " ".join(tokens)


def glossary_matches(normalised: str) -> list[tuple[str, str, str]]:
    """Return (matched_text, gloss, language) for each glossary entry found."""
    hits = []
    for pattern, gloss, lang in _COMPILED_GLOSSARY:
        m = pattern.search(normalised)
        if m:
            hits.append((m.group(0), gloss, lang))
    return hits


def enrich_text(normalised: str) -> str:
    """Append English glosses for supported code-mixed phrases."""
    hits = glossary_matches(normalised)
    if not hits:
        return normalised
    return normalised + " " + " ".join(g for _, g, _ in hits)


def language_hint(normalised: str) -> str:
    """Heuristic language hint based ONLY on the controlled glossary."""
    hits = glossary_matches(normalised)
    langs = [lang for _, _, lang in hits]
    regional = [lang for lang in langs if lang != "hi-Latn"]
    if regional:
        return max(set(regional), key=regional.count)
    if langs:
        return "hi-Latn"
    return "en"


def tokens(normalised: str) -> list[str]:
    return _WORD_RE.findall(normalised)


def extract_entities(normalised: str) -> frozenset[str]:
    return frozenset(e for e, pat in _ENTITY_PATTERNS if pat.search(normalised))


@lru_cache(maxsize=4096)
def _term_regex(term: str) -> re.Pattern:
    return re.compile(rf"\b{re.escape(term)}\b")


def find_term(normalised: str, term: str, absence_sensitive: bool = False) -> tuple[bool, bool]:
    """Search for ``term``. Returns (found, negated).

    A mention is *negated* if one of ``NEGATORS`` appears within the three
    preceding tokens (e.g. "no hygiene issues"). For absence-sensitive terms
    (e.g. "allergen information") a preceding negator describes the complaint
    itself ("no allergen information"), so negation is not applied.
    """
    found_any = False
    for m in _term_regex(term).finditer(normalised):
        found_any = True
        if absence_sensitive:
            return True, False
        preceding = normalised[: m.start()].split()[-3:]
        if not any(tok in NEGATORS for tok in preceding):
            return True, False
    return found_any, found_any


class TermMatcher:
    """Fast, negation-aware matching of a fixed list of terms (one compiled regex)."""

    def __init__(self, terms, absence_sensitive=()):
        self.terms = list(dict.fromkeys(terms))
        self.absence_sensitive = set(absence_sensitive)
        alternation = "|".join(re.escape(t) for t in sorted(self.terms, key=len, reverse=True))
        self._regex = re.compile(rf"\b(?:{alternation})\b") if self.terms else None

    def matches(self, normalised: str) -> list[str]:
        """Return the distinct terms found in the text that are not negated."""
        if self._regex is None:
            return []
        found: list[str] = []
        for m in self._regex.finditer(normalised):
            term = m.group(0)
            if term in found:
                continue
            if term not in self.absence_sensitive:
                preceding = normalised[: m.start()].split()[-3:]
                if any(tok in NEGATORS for tok in preceding):
                    continue
            found.append(term)
        return found


def matched_terms(normalised: str, terms, absence_sensitive=()) -> list[str]:
    """Return terms that occur in the text and are not negated."""
    return TermMatcher(terms, absence_sensitive).matches(normalised)


def preprocess_frame(df, text_col: str = "original_text"):
    """Add normalised/enriched/language/entity columns to a copy of ``df``."""
    out = df.copy()
    out["normalised_text"] = out[text_col].map(normalise_text)
    out["enriched_text"] = out["normalised_text"].map(enrich_text)
    out["language_hint"] = out["normalised_text"].map(language_hint)
    out["entities"] = out["normalised_text"].map(lambda t: sorted(extract_entities(t)))
    return out
