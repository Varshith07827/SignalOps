"""Central configuration for StorePulse.

Every tunable threshold used by the pipeline lives here so that behaviour is
transparent and can be changed without editing business logic. All values are
provisional defaults chosen for the synthetic demonstration dataset.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
GENERATED_DIR = DATA_DIR / "generated"
STATE_DIR = DATA_DIR / "state"
ARTIFACTS_DIR = ROOT_DIR / "artifacts"

RAW_FEEDBACK_PATH = GENERATED_DIR / "feedback_raw.parquet"
STORES_PATH = GENERATED_DIR / "stores.parquet"
TRAINING_CORPUS_PATH = GENERATED_DIR / "training_corpus.parquet"
SCENARIO_MANIFEST_PATH = GENERATED_DIR / "scenario_manifest.json"
ANALYTICS_DB_PATH = GENERATED_DIR / "storepulse.duckdb"
STATE_DB_PATH = STATE_DIR / "case_state.duckdb"
MODEL_PATH = ARTIFACTS_DIR / "classifier.joblib"
EVALUATION_REPORT_PATH = ARTIFACTS_DIR / "evaluation_report.json"
REPORTS_DIR = ARTIFACTS_DIR / "reports"


def ensure_directories() -> None:
    """Create runtime directories if they do not exist."""
    for path in (GENERATED_DIR, STATE_DIR, ARTIFACTS_DIR, REPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Schema: which columns may be used for inference
# --------------------------------------------------------------------------- #
# Only these columns are passed to the processing pipeline. Ground-truth
# columns produced by the synthetic generator are stripped before inference.
INFERENCE_COLUMNS = [
    "feedback_id",
    "timestamp",
    "store_id",
    "region",
    "channel",
    "original_text",
    "rating",
]

GROUND_TRUTH_COLUMNS = [
    "true_issue_category",
    "true_severity",
    "true_actionable",
    "incident_id",
    "is_planted_incident",
    "planted_scenario",
    "template_id",
    "template_split",
    "true_language",
]

CHANNELS = ["online_review", "in_app", "staff_note", "call_centre"]
CHANNEL_LABELS = {
    "online_review": "Online review",
    "in_app": "In-app rating",
    "staff_note": "Store staff note",
    "call_centre": "Call-centre transcript",
}


# --------------------------------------------------------------------------- #
# Component settings
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GeneratorSettings:
    n_records: int = 40_000
    seed: int = 20260
    n_weeks: int = 26
    end_date: str = "2026-09-27"  # last (Sunday) day of the synthetic period
    stores_per_region: int = 12
    duplicate_incident_rate: float = 0.14  # share of incidents reported more than once
    training_per_class: int = 260
    training_seed_offset: int = 1_000_003  # training corpus uses a different seed
    holdout_template_share: float = 0.25  # templates never shown to the classifier


@dataclass(frozen=True)
class ClassifierSettings:
    accept_threshold: float = 0.50  # >= : auto-classified
    review_threshold: float = 0.30  # >= : predicted but flagged for review
    rule_weight: float = 0.30  # share of rule evidence in the hybrid score
    min_known_token_share: float = 0.30  # below this (and no rule hits) -> unknown
    max_word_ngram: int = 2
    char_ngram_range: tuple[int, int] = (3, 5)
    C: float = 6.0


@dataclass(frozen=True)
class DedupSettings:
    window_hours: float = 36.0  # hard limit: candidates must be within this of the cluster anchor
    time_decay_hours: float = 8.0  # time proximity = exp(-hours_apart / decay)
    merge_threshold: float = 0.50
    possible_threshold: float = 0.40
    weight_text: float = 0.35
    weight_entity: float = 0.25
    weight_time: float = 0.40


@dataclass(frozen=True)
class DetectionSettings:
    current_window_days: int = 7  # reporting window shown to users
    scan_windows_days: tuple[int, ...] = (7, 14)  # multi-scale scan; Bonferroni-combined
    baseline_weeks: int = 12
    min_baseline_weeks: int = 6
    prior_strength_weeks: float = 4.0  # empirical-Bayes pseudo-weeks
    min_current_count: int = 3  # minimum unique incidents in current window
    min_absolute_increase: float = 2.0
    min_rate_ratio: float = 2.0
    network_ratio_bounds: tuple[float, float] = (0.8, 3.0)
    exposure_ratio_bounds: tuple[float, float] = (0.67, 1.5)
    dispersion_bounds: tuple[float, float] = (1.0, 3.0)
    # Benjamini-Hochberg false-discovery level, by category policy severity.
    fdr_by_severity: dict = field(
        default_factory=lambda: {"Critical": 0.10, "High": 0.05, "Medium": 0.02, "Low": 0.02}
    )
    watch_p_value: float = 0.001  # un-confirmed but notable signals


@dataclass(frozen=True)
class PrioritySettings:
    weights: dict = field(
        default_factory=lambda: {
            "severity": 0.35,
            "evidence": 0.25,
            "trend": 0.20,
            "breadth": 0.10,
            "persistence": 0.10,
        }
    )
    severity_scores: dict = field(
        default_factory=lambda: {"Critical": 1.0, "High": 0.75, "Medium": 0.45, "Low": 0.2}
    )
    case_window_days: int = 7


GENERATOR = GeneratorSettings()
CLASSIFIER = ClassifierSettings()
DEDUP = DedupSettings()
DETECTION = DetectionSettings()
PRIORITY = PrioritySettings()

CASE_STATUSES = ["New", "Under Review", "Assigned", "Resolved"]
VERIFICATION_STATES = [
    "Allegation (unverified)",
    "Under investigation",
    "Verified incident",
    "Not substantiated",
]

SYNTHETIC_DISCLAIMER = (
    "All data shown is synthetic and generated locally for demonstration. "
    "It does not represent any real retailer, and evaluation figures are not "
    "official hackathon results."
)
