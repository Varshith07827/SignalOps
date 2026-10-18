"""Deterministic synthetic retail-feedback generator.

Everything produced here is SYNTHETIC. The generator creates:

* a store master (5 regions x 12 stores, four store formats of different size);
* ``n_records`` feedback records across four channels over ``n_weeks`` weeks,
  with realistic volume differences, seasonality, duplicate reports of the same
  underlying incident, typos, abbreviations, emojis, Hinglish and a small set
  of transliterated regional phrases;
* three planted demonstration scenarios (A, B, C) documented in
  ``SCENARIO_SPECS`` and written to a manifest file;
* a separate labelled training corpus, generated with a different seed and
  restricted to "train" templates, so the classifier never sees the hold-out
  phrasings or the evaluation records.

Ground-truth columns (``true_*``, ``incident_id``, ``is_planted_incident`` ...)
exist for evaluation only and are stripped before inference.

Run ``python -m src.data_generator`` to (re)create the dataset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass

import numpy as np
import pandas as pd

import config
from src import phrasebank as pb
from src.taxonomy import CATEGORIES, CATEGORY_BY_CODE, CHANNEL_PROFILES, NO_ISSUE, OUT_OF_TAXONOMY

REGION_CITIES = {
    "North": ["Delhi", "Gurugram", "Noida", "Lucknow", "Chandigarh", "Jaipur"],
    "South": ["Bengaluru", "Chennai", "Hyderabad", "Kochi", "Coimbatore", "Mysuru"],
    "East": ["Kolkata", "Bhubaneswar", "Patna", "Guwahati", "Ranchi", "Siliguri"],
    "West": ["Mumbai", "Pune", "Ahmedabad", "Surat", "Nagpur", "Vadodara"],
    "Central": ["Bhopal", "Indore", "Raipur", "Jabalpur", "Gwalior", "Ujjain"],
}
LOCALITIES = ["Central", "Ring Road", "Market", "Station Road", "Tech Park", "Lake View", "Old Town",
              "Highway", "University", "Civil Lines"]
FORMAT_EXPOSURE = {"Express": 0.55, "Neighbourhood": 1.0, "Superstore": 1.7, "Hypermarket": 2.8}
FORMAT_PLAN = ["Express"] * 3 + ["Neighbourhood"] * 4 + ["Superstore"] * 3 + ["Hypermarket"] * 2

# Ground-truth template severity for categories whose policy floor differs from base.
DOW_WEIGHTS = np.array([0.88, 0.85, 0.9, 0.95, 1.05, 1.25, 1.2])  # Mon..Sun
HOUR_WEIGHTS = np.array([2, 3, 5, 7, 8, 7, 6, 5, 6, 8, 9, 8, 6, 4], dtype=float)  # 08:00..21:00
HOUR_WEIGHTS /= HOUR_WEIGHTS.sum()

SEASONALITY = {  # month -> multiplier (network-wide, by category)
    "store_temperature_ac": {4: 2.2, 5: 3.0, 6: 2.4, 7: 1.3, 8: 1.0, 9: 1.0},
    "refrigeration_failure": {4: 1.2, 5: 1.35, 6: 1.25},
    "delivery_delay": {7: 1.4, 8: 1.5},
}

# --------------------------------------------------------------------------- #
# Planted demonstration scenarios (our own test cases, NOT organiser incidents)
# --------------------------------------------------------------------------- #
SCENARIO_SPECS = {
    "A": {
        "name": "Emerging refrigeration failure",
        "category": "refrigeration_failure",
        "store_rule": {"region": "South", "format": "Neighbourhood"},
        "onset_days_before_end": 20,
        "weekly_episodes": [3, 5, 7],
        "reports_per_episode": [1, 4],
        "items": ["milk", "curd", "paneer", "butter", "yogurt"],
        "locs": ["dairy chiller", "chiller unit 2"],
        "channel_mix": {"online_review": 0.35, "in_app": 0.15, "staff_note": 0.30, "call_centre": 0.20},
        "expected_owner": "Store Ops",
        "description": "Store with a modest refrigeration baseline; chiller failure episodes rise over "
                       "three weeks and are reported through all four channels with varied wording.",
    },
    "B": {
        "name": "Single-report allergen labelling concern",
        "category": "allergen_labelling",
        "store_rule": {"region": "North", "format": "Express"},
        "days_before_end": 3,
        "expected_owner": "Merchandising",
        "description": "Exactly one call-centre report alleging a nut-free label on a product that lists "
                       "peanut traces, with a reported reaction. Must be escalated as Critical under "
                       "policy and remain an unverified allegation.",
    },
    "C": {
        "name": "Emerging digital payment failure",
        "category": "payment_failure",
        "store_rule": {"region": "West", "format": "Superstore"},
        "onset_days_before_end": 12,
        "weekly_episodes": [3, 9],  # first (partial) week, final week
        "reports_per_episode": [1, 3],
        "items": ["UPI", "card", "POS terminal", "QR code"],
        "locs": ["counter 3", "billing counter", "self checkout"],
        "channel_mix": {"online_review": 0.25, "in_app": 0.30, "staff_note": 0.15, "call_centre": 0.30},
        "expected_owner": "Digital",
        "description": "Payment-failure reports rise sharply at one store across app, review, call-centre "
                       "and staff channels.",
    },
}
NEGATIVE_CONTROLS = {
    "N1": "Chronic stock shortages at one Hypermarket (East): high but stable volume. Must NOT be "
          "flagged as emerging just because it has the largest totals.",
    "N2": "Network-wide seasonal rise in store-temperature/AC complaints (Apr-Jun). A store-level "
          "detector adjusted for network trend should not flag every store.",
}

SCENARIO_B_TEXT = (
    "Customer: I bought the BakeHouse Choco Crunch cookies from your {store} store on Thursday. "
    "The front of the pack says nut-free but the back label lists peanut traces. My son is allergic "
    "and had a reaction after eating two, we had to give him his medicine. Please check this batch "
    "urgently. Agent: Apologised, logged complaint ref CC-48213 and escalated to the store team."
)


# --------------------------------------------------------------------------- #
# Template catalogue with deterministic train / hold-out split
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Template:
    template_id: str
    category: str
    style: str  # en | hi | rg | staff
    language: str  # en | hi-Latn | ta | te | ...
    text: str
    critical: bool
    split: str  # train | holdout


def _stable_fraction(key: str) -> float:
    return int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF


def build_template_catalogue(holdout_share: float = config.GENERATOR.holdout_template_share) -> list[Template]:
    templates: list[Template] = []
    for cat, spec in pb.PHRASES.items():
        for style in ("en", "hi", "rg", "staff"):
            group = spec.get(style, [])
            group_templates = []
            for i, entry in enumerate(group):
                lang, text = entry if style == "rg" else ({"en": "en", "hi": "hi-Latn", "staff": "en"}[style], entry)
                critical = text.startswith("[C]")
                text = text[3:] if critical else text
                tid = f"{cat}:{style}:{i}"
                split = "holdout" if _stable_fraction(tid) < holdout_share else "train"
                group_templates.append(Template(tid, cat, style, lang, text, critical, split))
            # every group keeps at least one training template
            if group_templates and all(t.split == "holdout" for t in group_templates):
                t0 = group_templates[0]
                group_templates[0] = Template(t0.template_id, t0.category, t0.style, t0.language, t0.text,
                                              t0.critical, "train")
            templates.extend(group_templates)
    return templates


# --------------------------------------------------------------------------- #
# Store master
# --------------------------------------------------------------------------- #
def generate_store_master(seed: int = config.GENERATOR.seed,
                          stores_per_region: int = config.GENERATOR.stores_per_region) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    sid = 1
    for region, cities in REGION_CITIES.items():
        plan = list(FORMAT_PLAN) if stores_per_region == len(FORMAT_PLAN) else [
            FORMAT_PLAN[i % len(FORMAT_PLAN)] for i in range(stores_per_region)]
        plan = list(rng.permutation(plan))
        for i in range(stores_per_region):
            city = cities[i % len(cities)]
            locality = LOCALITIES[int(rng.integers(len(LOCALITIES)))]
            fmt = str(plan[i])
            rows.append({
                "store_id": f"S{sid:03d}",
                "store_name": f"{city} {locality}",
                "city": city,
                "region": region,
                "format": fmt,
                "footfall_index": round(FORMAT_EXPOSURE[fmt] * float(rng.uniform(0.85, 1.15)), 3),
                "digital_adoption": round(float(rng.uniform(0.6, 1.4)), 3),
            })
            sid += 1
    return pd.DataFrame(rows)


def select_scenario_stores(stores: pd.DataFrame) -> dict[str, str]:
    """Deterministically choose the store for each planted scenario."""
    chosen = {}
    for key, spec in SCENARIO_SPECS.items():
        rule = spec["store_rule"]
        match = stores[(stores.region == rule["region"]) & (stores.format == rule["format"])]
        chosen[key] = str(match.sort_values("store_id").iloc[0].store_id)
    east_hyper = stores[(stores.region == "East") & (stores.format == "Hypermarket")]
    chosen["N1"] = str(east_hyper.sort_values("store_id").iloc[0].store_id)
    return chosen


# --------------------------------------------------------------------------- #
# Text rendering
# --------------------------------------------------------------------------- #
class TextRenderer:
    def __init__(self, rnd: random.Random, templates: list[Template], allowed_splits=("train", "holdout")):
        self.rnd = rnd
        self.by_cat_style: dict[tuple[str, str], list[Template]] = {}
        for t in templates:
            if t.split in allowed_splits:
                self.by_cat_style.setdefault((t.category, t.style), []).append(t)

    def pick_template(self, category: str, channel: str) -> Template:
        rnd = self.rnd
        staff = self.by_cat_style.get((category, "staff"), [])
        if channel == "staff_note" and staff and rnd.random() < 0.65:
            return rnd.choice(staff)
        u = rnd.random()
        style = "en" if u < 0.68 else ("hi" if u < 0.93 else "rg")
        pool = self.by_cat_style.get((category, style)) or self.by_cat_style.get((category, "en"))
        if not pool:
            pool = self.by_cat_style.get((category, "hi")) or staff
        return rnd.choice(pool)

    def _fill(self, text: str, category: str, item: str, loc: str) -> str:
        rnd = self.rnd
        amt = rnd.choice([f"Rs {rnd.randint(20, 900)}", f"₹{rnd.randint(20, 900)}", f"{rnd.randint(20, 900)} rs"])
        return text.format(item=item, loc=loc, amt=amt, n=rnd.randint(2, 15))

    def _noise(self, text: str, channel: str, category: str, truncate_ok: bool) -> tuple[str, bool]:
        rnd = self.rnd
        heavy = channel in ("staff_note", "in_app")
        words = text.split()
        out = []
        for w in words:
            core = w.strip(".,!?'\"").lower()
            if core in pb.ABBREVIATIONS and rnd.random() < (0.55 if heavy else 0.25):
                w = w.lower().replace(core, rnd.choice(pb.ABBREVIATIONS[core]))
            elif len(core) > 3 and core.isalpha() and rnd.random() < (0.05 if heavy else 0.03):
                w = _typo(rnd, w)
            out.append(w)
        text = " ".join(out)
        r = rnd.random()
        if r < (0.55 if heavy else 0.25):
            text = text.lower()
        elif r > 0.98:
            text = text.upper()
        if rnd.random() < 0.08:
            text = text.replace("very ", "sooo ").replace("Very ", "Sooo ")
        if rnd.random() < 0.12:
            text = text.rstrip(".") + rnd.choice(["!!", "!!!", "??", " ..."])
        emoji_p = 0.45 if channel == "in_app" else (0.2 if channel == "online_review" else 0.03)
        if rnd.random() < emoji_p:
            tone = pb.CATEGORY_TONE.get(category, "negative")
            text = text + " " + rnd.choice(pb.EMOJI_BY_TONE[tone])
        truncated = False
        if truncate_ok and rnd.random() < 0.04 and len(text.split()) > 8:
            ws = text.split()
            keep = max(4, int(len(ws) * rnd.uniform(0.5, 0.8)))
            text = " ".join(ws[:keep]) + "..."
            truncated = True
        return text, truncated

    def render(self, template: Template, channel: str, store: dict, item: str, loc: str,
               truncate_ok: bool = True) -> tuple[str, bool]:
        rnd = self.rnd
        category = template.category
        core = self._fill(template.text, category, item, loc)
        positive = category == NO_ISSUE
        if channel == "online_review":
            prefix = rnd.choice(pb.REVIEW_PREFIXES).format(store=store["store_name"],
                                                           dow=rnd.choice(pb.DAYS_OF_WEEK))
            suffix = rnd.choice(pb.POSITIVE_SUFFIXES if positive else pb.REVIEW_SUFFIXES)
            text = f"{prefix}{core}{suffix}"
        elif channel == "staff_note":
            prefix = rnd.choice(pb.STAFF_PREFIXES).format(store_id=store["store_id"])
            text = f"{prefix}{core}{rnd.choice(pb.STAFF_SUFFIXES)}"
        elif channel == "call_centre":
            ack = rnd.choice(pb.CALL_ACKS).format(ref=f"CC-{rnd.randint(10000, 99999)}")
            text = f"{rnd.choice(pb.CALL_OPENERS)}{core}{ack}"
        else:
            text = core
        return self._noise(text, channel, category, truncate_ok)


def _typo(rnd: random.Random, word: str) -> str:
    letters = list(word)
    idx = [i for i, ch in enumerate(letters) if ch.isalpha()]
    if len(idx) < 4:
        return word
    i = rnd.choice(idx[1:-1])
    op = rnd.random()
    if op < 0.4 and i + 1 < len(letters):
        letters[i], letters[i + 1] = letters[i + 1], letters[i]
    elif op < 0.7:
        del letters[i]
    else:
        letters.insert(i, letters[i])
    return "".join(letters)


def _rating(rnd: random.Random, channel: str, category: str):
    if channel not in ("online_review", "in_app"):
        return np.nan
    if category == NO_ISSUE:
        return float(rnd.choices([5, 4, 3], weights=[0.6, 0.35, 0.05])[0])
    if category == OUT_OF_TAXONOMY:
        return float(rnd.choices([2, 3, 4], weights=[0.3, 0.4, 0.3])[0])
    return float(rnd.choices([1, 2, 3, 4], weights=[0.5, 0.3, 0.15, 0.05])[0])


def _true_severity(category: str, critical_template: bool) -> str:
    if category in (NO_ISSUE, OUT_OF_TAXONOMY):
        return "Low"
    if critical_template:
        return "Critical"
    return CATEGORY_BY_CODE[category].base_severity


def _channel_weights(category: str, store: dict) -> dict[str, float]:
    if category == OUT_OF_TAXONOMY:
        profile = CHANNEL_PROFILES["praise"]
    else:
        profile = CHANNEL_PROFILES[CATEGORY_BY_CODE[category].channel_profile]
    w = dict(profile)
    w["in_app"] = w["in_app"] * store["digital_adoption"]
    return w


def _choose(rnd: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights)
    return rnd.choices(keys, weights=[weights[k] for k in keys])[0]


# --------------------------------------------------------------------------- #
# Main dataset
# --------------------------------------------------------------------------- #
def _date_index(settings: config.GeneratorSettings) -> pd.DatetimeIndex:
    end = pd.Timestamp(settings.end_date)
    return pd.date_range(end - pd.Timedelta(days=7 * settings.n_weeks - 1), end, freq="D")


def generate_dataset(settings: config.GeneratorSettings = config.GENERATOR
                     ) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Generate (feedback, stores, manifest). Fully deterministic for a given seed."""
    rng = np.random.default_rng(settings.seed)
    rnd = random.Random(settings.seed)
    stores = generate_store_master(settings.seed, settings.stores_per_region)
    store_rows = stores.to_dict("records")
    store_by_id = {s["store_id"]: s for s in store_rows}
    chosen = select_scenario_stores(stores)
    templates = build_template_catalogue(settings.holdout_template_share)
    renderer = TextRenderer(rnd, templates)
    days = _date_index(settings)
    n_days = len(days)

    # ---- planted scenarios first (so we know how many background records to make)
    planted = _generate_planted(rng, rnd, renderer, settings, days, chosen, store_by_id)
    n_background = settings.n_records - len(planted)

    # ---- background expected-volume tensor  E[store, category, day]
    gen_categories = [c.code for c in CATEGORIES] + [OUT_OF_TAXONOMY]
    base = np.array([CATEGORY_BY_CODE[c].base_rate if c in CATEGORY_BY_CODE else 1.4 for c in gen_categories])
    exposure = stores.footfall_index.to_numpy()
    S, C, D = len(store_rows), len(gen_categories), n_days
    season = np.ones((C, D))
    months = days.month.to_numpy()
    for ci, code in enumerate(gen_categories):
        for month, mult in SEASONALITY.get(code, {}).items():
            season[ci, months == month] = mult
    trend = np.linspace(0.95, 1.05, D)
    day_w = DOW_WEIGHTS[days.dayofweek.to_numpy()] * trend
    store_mult = rng.lognormal(0.0, 0.3, size=(S, C))
    n1_idx = stores.index[stores.store_id == chosen["N1"]][0]
    store_mult[n1_idx, gen_categories.index("stock_shortage")] = 4.0  # negative control N1
    week_of_day = np.arange(D) // 7
    weekly_noise = rng.gamma(10.0, 1 / 10.0, size=(S, C, settings.n_weeks))[:, :, week_of_day]
    E = (exposure[:, None, None] * base[None, :, None] * season[None, :, :] * day_w[None, None, :]
         * store_mult[:, :, None] * weekly_noise)
    P = (E / E.sum()).ravel()

    mean_reports = 1 + settings.duplicate_incident_rate * 1.5
    n_inc = int(n_background / mean_reports * 1.08)
    counts = rng.multinomial(n_inc, P)
    flat = np.repeat(np.arange(P.size), counts)
    rng.shuffle(flat)
    s_idx, c_idx, d_idx = np.unravel_index(flat, (S, C, D))
    extra = np.where(rng.random(flat.size) < settings.duplicate_incident_rate,
                     rng.choice([1, 2, 3], size=flat.size, p=[0.6, 0.3, 0.1]), 0)
    n_reports = 1 + extra
    cum = np.cumsum(n_reports)
    last = int(np.searchsorted(cum, n_background))
    n_reports = n_reports[: last + 1].copy()
    n_reports[-1] -= int(cum[last] - n_background)
    end_ts = days[-1] + pd.Timedelta(hours=23, minutes=59)

    records = []
    for k in range(last + 1):
        store = store_rows[s_idx[k]]
        category = gen_categories[c_idx[k]]
        day = days[d_idx[k]]
        spec = pb.PHRASES[category]
        item, loc = rnd.choice(spec["items"]), rnd.choice(spec["locs"])
        hour = 8 + int(rng.choice(len(HOUR_WEIGHTS), p=HOUR_WEIGHTS))
        t0 = day + pd.Timedelta(hours=hour, minutes=rnd.randint(0, 59))
        incident_id = f"INC{k + 1:06d}"
        first_template = None
        for r in range(int(n_reports[k])):
            channel = _choose(rnd, _channel_weights(category, store))
            if r == 0 or rnd.random() >= 0.5:
                template = renderer.pick_template(category, channel)
            else:
                template = first_template
                if template.style == "staff" and channel != "staff_note":
                    template = renderer.pick_template(category, channel)
            first_template = first_template or template
            if r > 0 and rnd.random() > 0.85:
                item, loc = rnd.choice(spec["items"]), rnd.choice(spec["locs"])
            ts = t0 if r == 0 else min(t0 + pd.Timedelta(hours=min(rnd.expovariate(1 / 4.0), 30)), end_ts)
            text, _ = renderer.render(template, channel, store, item, loc)
            records.append(_record(ts, store, channel, text, category, template, incident_id,
                                   rnd, planted=None))

    df = pd.DataFrame(records + planted)
    df = df.sort_values(["timestamp", "store_id", "channel", "original_text"], kind="mergesort").reset_index(drop=True)
    df.insert(0, "feedback_id", [f"FB{i + 1:06d}" for i in range(len(df))])
    df["timestamp"] = pd.to_datetime(df["timestamp"]).astype("datetime64[us]")

    manifest = _manifest(settings, df, chosen, stores)
    return df, stores, manifest


def _record(ts, store, channel, text, category, template, incident_id, rnd, planted: str | None) -> dict:
    return {
        "timestamp": ts,
        "store_id": store["store_id"],
        "store_name": store["store_name"],
        "region": store["region"],
        "channel": channel,
        "original_text": text,
        "rating": _rating(rnd, channel, category),
        "true_issue_category": category,
        "true_severity": _true_severity(category, template.critical if template else True),
        "true_actionable": category not in (NO_ISSUE, OUT_OF_TAXONOMY),
        "incident_id": incident_id,
        "is_planted_incident": planted is not None,
        "planted_scenario": planted or "",
        "template_id": template.template_id if template else "scenario_b_fixed",
        "template_split": template.split if template else "holdout",
        "true_language": template.language if template else "en",
    }


def _generate_planted(rng, rnd, renderer, settings, days, chosen, store_by_id) -> list[dict]:
    end_day = days[-1]
    records: list[dict] = []
    for key in ("A", "C"):
        spec = SCENARIO_SPECS[key]
        store = store_by_id[chosen[key]]
        onset_day = end_day - pd.Timedelta(days=spec["onset_days_before_end"])
        total_days = spec["onset_days_before_end"] + 1
        n_weeks = len(spec["weekly_episodes"])
        # split the incident window into consecutive blocks; the last block is the final week
        boundaries = [0]
        if n_weeks == 3:
            boundaries = [0, 7, 14, total_days]
        else:
            boundaries = [0, total_days - 7, total_days]
        episode = 0
        for w, n_ep in enumerate(spec["weekly_episodes"]):
            lo, hi = boundaries[w], boundaries[w + 1]
            ep_days = sorted(rnd.choices(range(lo, hi), k=n_ep)) if n_ep > hi - lo else sorted(
                rnd.sample(range(lo, hi), n_ep))
            if w == 0:
                ep_days[0] = 0  # onset = first episode on the onset day
            for d in ep_days:
                episode += 1
                inc_id = f"PLANT-{key}-{episode:02d}"
                hour = rnd.randint(9, 19)
                t0 = onset_day + pd.Timedelta(days=d, hours=hour, minutes=rnd.randint(0, 59))
                item, loc = rnd.choice(spec["items"]), rnd.choice(spec["locs"])
                lo_r, hi_r = spec["reports_per_episode"]
                for r in range(rnd.randint(lo_r, hi_r)):
                    channel = _choose(rnd, spec["channel_mix"])
                    template = renderer.pick_template(spec["category"], channel)
                    ts = t0 + pd.Timedelta(minutes=0 if r == 0 else rnd.randint(20, 300))
                    ts = min(ts, end_day + pd.Timedelta(hours=23, minutes=59))
                    text, _ = renderer.render(template, channel, store, item, loc, truncate_ok=False)
                    records.append(_record(ts, store, channel, text, spec["category"], template, inc_id,
                                           rnd, planted=key))
    # Scenario B: exactly one report
    spec = SCENARIO_SPECS["B"]
    store = store_by_id[chosen["B"]]
    ts = end_day - pd.Timedelta(days=spec["days_before_end"]) + pd.Timedelta(hours=11, minutes=20)
    rec = _record(ts, store, "call_centre", SCENARIO_B_TEXT.format(store=store["store_name"]),
                  spec["category"], None, "PLANT-B-01", rnd, planted="B")
    rec["true_severity"] = "Critical"
    records.append(rec)
    return records


def _manifest(settings, df, chosen, stores) -> dict:
    scen = {}
    for key, spec in SCENARIO_SPECS.items():
        rows = df[df.planted_scenario == key]
        store = stores[stores.store_id == chosen[key]].iloc[0]
        scen[key] = {
            "name": spec["name"],
            "category": spec["category"],
            "store_id": chosen[key],
            "store_name": store.store_name,
            "region": store.region,
            "format": store.format,
            "expected_owner": spec["expected_owner"],
            "description": spec["description"],
            "n_reports": int(len(rows)),
            "n_true_incidents": int(rows.incident_id.nunique()),
            "channels": sorted(rows.channel.unique().tolist()),
            "onset": str(rows.timestamp.min()),
            "last_report": str(rows.timestamp.max()),
            "feedback_ids": rows.feedback_id.tolist() if key == "B" else None,
        }
    return {
        "generator": {"seed": settings.seed, "n_records": int(len(df)), "n_weeks": settings.n_weeks,
                      "start": str(df.timestamp.min().date()), "end": settings.end_date},
        "onset_definition": "Onset = timestamp of the first synthetic report belonging to the planted "
                            "scenario. Detection time = end of the first as-of day on which the detector, "
                            "using only data up to that moment, raises a confirmed flag for the "
                            "scenario's store and category.",
        "scenarios": scen,
        "negative_controls": {
            "N1": {"store_id": chosen["N1"], "category": "stock_shortage", "description": NEGATIVE_CONTROLS["N1"]},
            "N2": {"store_id": None, "category": "store_temperature_ac", "description": NEGATIVE_CONTROLS["N2"]},
        },
        "disclaimer": config.SYNTHETIC_DISCLAIMER,
    }


# --------------------------------------------------------------------------- #
# Training corpus (separate seed, train templates only)
# --------------------------------------------------------------------------- #
def generate_training_corpus(settings: config.GeneratorSettings = config.GENERATOR) -> pd.DataFrame:
    seed = settings.seed + settings.training_seed_offset
    rnd = random.Random(seed)
    stores = generate_store_master(settings.seed, settings.stores_per_region).to_dict("records")
    templates = build_template_catalogue(settings.holdout_template_share)
    renderer = TextRenderer(rnd, templates, allowed_splits=("train",))
    rows = []
    for cat in CATEGORIES:  # 'other' (out-of-taxonomy) is intentionally excluded
        spec = pb.PHRASES[cat.code]
        for _ in range(settings.training_per_class):
            store = rnd.choice(stores)
            channel = _choose(rnd, _channel_weights(cat.code, store))
            template = renderer.pick_template(cat.code, channel)
            text, _ = renderer.render(template, channel, store, rnd.choice(spec["items"]), rnd.choice(spec["locs"]))
            rows.append({"text": text, "label": cat.code, "template_id": template.template_id, "channel": channel})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Validation and persistence
# --------------------------------------------------------------------------- #
REQUIRED_COLUMNS = {
    "feedback_id": "object", "timestamp": "datetime64", "store_id": "object", "store_name": "object",
    "region": "object", "channel": "object", "original_text": "object", "rating": "float",
    "true_issue_category": "object", "true_severity": "object", "true_actionable": "bool",
    "incident_id": "object", "is_planted_incident": "bool", "planted_scenario": "object",
}


def validate_dataset(df: pd.DataFrame, stores: pd.DataFrame | None = None) -> list[str]:
    """Return a list of schema/consistency problems (empty list means valid)."""
    problems = []
    for col, kind in REQUIRED_COLUMNS.items():
        if col not in df.columns:
            problems.append(f"missing column: {col}")
            continue
        dtype = str(df[col].dtype)
        if kind == "datetime64" and not dtype.startswith("datetime64"):
            problems.append(f"{col} must be datetime, got {dtype}")
        if kind == "float" and not dtype.startswith("float"):
            problems.append(f"{col} must be float, got {dtype}")
        if kind == "bool" and dtype != "bool":
            problems.append(f"{col} must be bool, got {dtype}")
    if problems:
        return problems
    if df.feedback_id.duplicated().any():
        problems.append("duplicate feedback_id values")
    if df.original_text.isna().any() or (df.original_text.str.len() == 0).any():
        problems.append("empty original_text")
    bad_channels = set(df.channel) - set(config.CHANNELS)
    if bad_channels:
        problems.append(f"unknown channels: {bad_channels}")
    valid_cats = {c.code for c in CATEGORIES} | {OUT_OF_TAXONOMY}
    if set(df.true_issue_category) - valid_cats:
        problems.append("unknown ground-truth categories")
    if set(df.true_severity) - {"Critical", "High", "Medium", "Low"}:
        problems.append("unknown severities")
    rated = df.channel.isin(["online_review", "in_app"])
    if df.loc[rated, "rating"].isna().any() or df.loc[~rated, "rating"].notna().any():
        problems.append("rating must be present only for review/app channels")
    if not df.loc[rated, "rating"].between(1, 5).all():
        problems.append("rating out of range")
    if stores is not None and set(df.store_id) - set(stores.store_id):
        problems.append("feedback references unknown store_id")
    return problems


def save_dataset(df: pd.DataFrame, stores: pd.DataFrame, manifest: dict, training: pd.DataFrame | None = None):
    config.ensure_directories()
    df.to_parquet(config.RAW_FEEDBACK_PATH, index=False)
    stores.to_parquet(config.STORES_PATH, index=False)
    config.SCENARIO_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    if training is not None:
        training.to_parquet(config.TRAINING_CORPUS_PATH, index=False)


def load_raw() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    df = pd.read_parquet(config.RAW_FEEDBACK_PATH)
    stores = pd.read_parquet(config.STORES_PATH)
    manifest = json.loads(config.SCENARIO_MANIFEST_PATH.read_text(encoding="utf-8"))
    return df, stores, manifest


def dataset_exists() -> bool:
    return all(p.exists() for p in (config.RAW_FEEDBACK_PATH, config.STORES_PATH,
                                    config.SCENARIO_MANIFEST_PATH, config.TRAINING_CORPUS_PATH))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate the StorePulse synthetic dataset.")
    parser.add_argument("--records", type=int, default=config.GENERATOR.n_records)
    parser.add_argument("--seed", type=int, default=config.GENERATOR.seed)
    args = parser.parse_args(argv)
    settings = config.GeneratorSettings(n_records=args.records, seed=args.seed)
    df, stores, manifest = generate_dataset(settings)
    problems = validate_dataset(df, stores)
    if problems:
        print("Validation FAILED:", *problems, sep="\n  ")
        return 1
    training = generate_training_corpus(settings)
    save_dataset(df, stores, manifest, training)
    print(f"Generated {len(df):,} synthetic feedback records for {len(stores)} stores "
          f"({manifest['generator']['start']} to {manifest['generator']['end']}).")
    print(f"Training corpus: {len(training):,} records (separate seed, train templates only).")
    for key, sc in manifest["scenarios"].items():
        print(f"  Scenario {key}: {sc['name']} @ {sc['store_id']} ({sc['store_name']}, {sc['region']}) "
              f"- {sc['n_reports']} reports, onset {sc['onset']}")
    print(f"Saved to {config.GENERATED_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
