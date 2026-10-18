"""End-to-end processing pipeline.

Feedback -> normalisation -> classification -> severity/policy -> deduplication
-> emerging-issue detection -> prioritised cases -> DuckDB.

Run ``python -m src.pipeline`` (add ``--regenerate`` / ``--retrain`` to rebuild
the synthetic data or the model first).

Leakage guard: ``strip_ground_truth`` keeps only ``config.INFERENCE_COLUMNS``
before any model or rule sees the data; synthetic ground-truth columns are
only used later by ``src.evaluation``.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime

import pandas as pd

import config
from src import anomaly_detection, data_generator, deduplication, prioritization, routing, storage
from src import preprocessing as pp
from src.classifier import DECISION_LABELS, HybridClassifier, load_or_train, train_from_corpus
from src.severity import PolicyEngine
from src.taxonomy import TAXONOMY_VERSION, category_label


def strip_ground_truth(df: pd.DataFrame) -> pd.DataFrame:
    """Return only inference-safe columns (raises if any are missing)."""
    missing = [c for c in config.INFERENCE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing inference columns: {missing}")
    clean = df[config.INFERENCE_COLUMNS].copy()
    assert not set(clean.columns) & set(config.GROUND_TRUTH_COLUMNS)
    return clean


def process_feedback(raw: pd.DataFrame, stores: pd.DataFrame, clf: HybridClassifier,
                     policy: PolicyEngine | None = None) -> pd.DataFrame:
    """Classify, assess severity, route and deduplicate. Ground truth is never used."""
    df = strip_ground_truth(raw).reset_index(drop=True)
    policy = policy or PolicyEngine()
    df = pp.preprocess_frame(df)
    preds = clf.predict_frame(df["original_text"])
    df = pd.concat([df, preds], axis=1)
    df["decision_label"] = df["decision"].map(DECISION_LABELS)
    df["category_label"] = df["pred_category"].map(category_label)
    df = pd.concat([df, policy.assess_frame(df)], axis=1)
    owners = df["pred_category"].map(routing.assign_owner)
    df["owner"] = owners.map(lambda o: o[0])
    df["secondary_owner"] = owners.map(lambda o: o[1] or "")
    df = pd.concat([df, deduplication.deduplicate(df)], axis=1)
    df = df.merge(stores[["store_id", "store_name", "format"]], on="store_id", how="left")
    df = df.rename(columns={"format": "store_format"})
    df["week_start"] = df["timestamp"].dt.to_period("W-SUN").dt.start_time
    return df.drop(columns=["enriched_text"])


def analyse(processed: pd.DataFrame, stores: pd.DataFrame, as_of=None) -> dict[str, pd.DataFrame]:
    """Emerging-issue detection and case building at ``as_of`` (default: last day of data)."""
    as_of = pd.Timestamp(as_of or processed["timestamp"].max()).normalize()
    cells = anomaly_detection.score_cells(processed, stores, as_of)
    signals = anomaly_detection.detect_emerging(processed, stores, as_of, cells=cells)
    cases = prioritization.build_cases(processed, stores, signals, cells, as_of)
    return {"cells": cells, "signals": signals, "cases": cases, "as_of": as_of}


def run_pipeline(regenerate: bool = False, retrain: bool = False, verbose: bool = True) -> dict:
    t0 = time.time()
    config.ensure_directories()
    log = print if verbose else (lambda *a, **k: None)
    if regenerate or not data_generator.dataset_exists():
        log("Generating synthetic dataset ...")
        df, stores, manifest = data_generator.generate_dataset()
        problems = data_generator.validate_dataset(df, stores)
        if problems:
            raise RuntimeError(f"Generated dataset failed validation: {problems}")
        data_generator.save_dataset(df, stores, manifest, data_generator.generate_training_corpus())
        retrain = True
    raw, stores, manifest = data_generator.load_raw()
    if retrain or not config.MODEL_PATH.exists():
        log("Training classifier on the synthetic training corpus ...")
        clf = train_from_corpus()
    else:
        clf = load_or_train()
    log(f"Processing {len(raw):,} records ...")
    processed = process_feedback(raw, stores, clf)
    res = analyse(processed, stores)
    signals, cases = res["signals"], res["cases"]
    signal_cols = [c for c in signals.columns if c not in ("flagged", "watch")] if len(signals) else []
    meta = {
        "as_of": str(res["as_of"].date()),
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "n_records": int(len(processed)),
        "n_unique_incidents": int(processed["cluster_id"].nunique()),
        "data_start": str(processed["timestamp"].min().date()),
        "data_end": str(processed["timestamp"].max().date()),
        "taxonomy_version": TAXONOMY_VERSION,
        "model": {k: v for k, v in clf.metadata.items() if k != "classes"},
        "seed": manifest["generator"]["seed"],
        "runtime_seconds": None,
    }
    storage.write_tables({
        "feedback": processed,
        "stores": stores,
        "signals": signals[signal_cols + ["flagged"]] if len(signals) else pd.DataFrame(),
        "cases": cases,
    })
    meta["runtime_seconds"] = round(time.time() - t0, 1)
    storage.write_meta(meta)
    storage.init_state()
    log(f"Done in {meta['runtime_seconds']}s: {meta['n_records']:,} records, "
        f"{meta['n_unique_incidents']:,} estimated unique incidents, "
        f"{int(signals['flagged'].sum()) if len(signals) else 0} emerging signals, {len(cases)} cases "
        f"(as of {meta['as_of']}).")
    return {"processed": processed, "stores": stores, "manifest": manifest, **res, "meta": meta}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the StorePulse processing pipeline.")
    parser.add_argument("--regenerate", action="store_true", help="Regenerate the synthetic dataset first")
    parser.add_argument("--retrain", action="store_true", help="Retrain the classifier first")
    args = parser.parse_args(argv)
    out = run_pipeline(regenerate=args.regenerate, retrain=args.retrain)
    top = out["cases"].head(8)
    if len(top):
        print("\nTop cases:")
        for r in top.itertuples():
            print(f"  [{r.tier_label.split(' - ')[0]}] {r.priority_score:5.1f}  {r.case_id:<45} "
                  f"{r.category_label:<32} {r.severity:<8} -> {r.owner}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
