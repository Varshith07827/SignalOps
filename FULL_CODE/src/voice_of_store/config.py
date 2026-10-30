"""Load settings from config.toml into typed, immutable objects."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

FULL_CODE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = FULL_CODE_DIR / "config.toml"


@dataclass(frozen=True)
class PathSettings:
    data_dir: Path
    outputs_dir: Path
    submission_dir: Path


@dataclass(frozen=True)
class ClassifierSettings:
    seed: int
    cv_folds: int
    issue_c: float
    severity_c: float
    actionable_c: float
    word_ngram_max: int
    char_ngram_min: int
    char_ngram_max: int
    char_min_df: int


@dataclass(frozen=True)
class DetectorSettings:
    prior_strength: float
    history_weeks: int
    gap_weeks: int
    min_history_weeks: int
    scan_windows: tuple[int, ...]
    chain_ratio_min: float
    chain_ratio_max: float
    min_count_policy: int
    min_count_other: int
    policy_weight: float
    p_value_threshold: float
    max_flags_per_week: int
    cooldown_weeks: int


@dataclass(frozen=True)
class DedupSettings:
    window_hours: float


@dataclass(frozen=True)
class BriefSettings:
    top_n: int
    quotes_per_issue: int
    quote_max_chars: int


@dataclass(frozen=True)
class RoutingSettings:
    sla_hours_critical: int
    sla_hours_high: int
    sla_hours_medium: int


@dataclass(frozen=True)
class EvaluationSettings:
    evaluator_path: Path
    timeout_seconds: int


@dataclass(frozen=True)
class ServerSettings:
    host: str
    port: int
    max_upload_mb: int


@dataclass(frozen=True)
class Settings:
    paths: PathSettings
    classifier: ClassifierSettings
    detector: DetectorSettings
    dedup: DedupSettings
    brief: BriefSettings
    routing: RoutingSettings
    evaluation: EvaluationSettings
    server: ServerSettings


def load_settings(path: Path | None = None) -> Settings:
    """Read the TOML settings file (``VOS_CONFIG`` overrides the default location)."""
    config_path = Path(path or os.environ.get("VOS_CONFIG", DEFAULT_CONFIG_PATH)).resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    base = config_path.parent
    paths = raw["paths"]
    detector = dict(raw["detector"])
    detector["scan_windows"] = tuple(int(w) for w in detector["scan_windows"])
    evaluation = dict(raw["evaluation"])
    evaluation["evaluator_path"] = (base / evaluation["evaluator_path"]).resolve()
    return Settings(
        paths=PathSettings(
            data_dir=(base / paths["data_dir"]).resolve(),
            outputs_dir=(base / paths["outputs_dir"]).resolve(),
            submission_dir=(base / paths["submission_dir"]).resolve(),
        ),
        classifier=ClassifierSettings(**raw["classifier"]),
        detector=DetectorSettings(**detector),
        dedup=DedupSettings(**raw["dedup"]),
        brief=BriefSettings(**raw["brief"]),
        routing=RoutingSettings(**raw["routing"]),
        evaluation=EvaluationSettings(**evaluation),
        server=ServerSettings(**raw["server"]),
    )
