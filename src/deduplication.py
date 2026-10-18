"""Conservative duplicate-report detection and canonical incident clustering.

Two reports are only *candidates* for the same incident when they share the
same store AND predicted category AND fall within ``window_hours`` of the
cluster's first (anchor) report. Candidates are then scored on

    score = w_text * text_cosine + w_entity * entity_jaccard + w_time * exp(-hours_apart / decay)

* ``score >= merge_threshold``    -> merged into the cluster (``merged duplicate``)
* ``score >= possible_threshold`` -> NOT merged, but flagged ``possible duplicate``
* otherwise                       -> a new, separate incident

Clusters are anchored on their first report, so a long run of similar
complaints cannot chain into a single giant incident. Records are processed in
time order and only ever compared with earlier records, so cluster assignments
use no future information. Every original record is preserved.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

import config
from src.taxonomy import UNCLASSIFIED


def pair_score(cosine: float, entities_a: frozenset, entities_b: frozenset, hours_apart: float,
               settings: config.DedupSettings = config.DEDUP) -> float:
    union = entities_a | entities_b
    jaccard = len(entities_a & entities_b) / len(union) if union else 0.0
    time_score = math.exp(-hours_apart / settings.time_decay_hours)
    return settings.weight_text * cosine + settings.weight_entity * jaccard + settings.weight_time * time_score


def deduplicate(df: pd.DataFrame, settings: config.DedupSettings = config.DEDUP) -> pd.DataFrame:
    """Return a frame (same index as ``df``) with cluster assignments.

    Requires columns: timestamp, store_id, pred_category, normalised_text, entities.
    """
    work = df[["timestamp", "store_id", "pred_category", "normalised_text", "entities"]].copy()
    work["_pos"] = np.arange(len(work))
    # min_df=2 drops one-off n-grams on large batches; on small batches it would keep only the
    # n-grams shared by every document and inflate similarity, so use min_df=1 there.
    min_df = 2 if len(work) >= 1000 else 1
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=min_df, sublinear_tf=True)
    X = normalize(vec.fit_transform(work["normalised_text"].fillna("")))
    ent = [frozenset(e) for e in work["entities"]]
    ts = work["timestamp"].to_numpy().astype("datetime64[s]").astype(np.int64) / 3600.0

    n = len(work)
    cluster_of = np.full(n, -1, dtype=np.int64)
    status = np.array(["unique"] * n, dtype=object)
    score_out = np.zeros(n)
    possible_of = np.full(n, -1, dtype=np.int64)

    order = work.sort_values(["timestamp", "_pos"], kind="mergesort")
    next_cluster = 0
    open_clusters: dict[tuple, list] = {}  # (store, category) -> [[anchor_time, cluster_id, member_positions]]
    for pos, store, cat in zip(order["_pos"].to_numpy(), order["store_id"].to_numpy(),
                               order["pred_category"].to_numpy()):
        if cat == UNCLASSIFIED:
            cluster_of[pos] = next_cluster
            next_cluster += 1
            continue
        key = (store, cat)
        clusters = open_clusters.setdefault(key, [])
        t = ts[pos]
        clusters[:] = [c for c in clusters if t - c[0] <= settings.window_hours]
        best_score, best_cluster = 0.0, None
        for c in clusters:
            for m in c[2]:
                cos = float(X[pos].multiply(X[m]).sum())
                s = pair_score(cos, ent[pos], ent[m], abs(t - ts[m]), settings)
                if s > best_score:
                    best_score, best_cluster = s, c
        if best_cluster is not None and best_score >= settings.merge_threshold:
            best_cluster[2].append(pos)
            cluster_of[pos] = best_cluster[1]
            status[pos] = "merged duplicate"
            score_out[pos] = best_score
            continue
        if best_cluster is not None and best_score >= settings.possible_threshold:
            status[pos] = "possible duplicate"
            possible_of[pos] = best_cluster[1]
            score_out[pos] = best_score
        cluster_of[pos] = next_cluster
        clusters.append([t, next_cluster, [pos]])
        next_cluster += 1

    out = pd.DataFrame(index=df.index)
    out["cluster_id"] = [f"CL{c:06d}" for c in cluster_of]
    out["dup_status"] = status
    out["dup_score"] = np.round(score_out, 3)
    out["possible_duplicate_of"] = [f"CL{c:06d}" if c >= 0 else "" for c in possible_of]
    sizes = out["cluster_id"].map(out["cluster_id"].value_counts())
    out["cluster_size"] = sizes.astype(int)
    first_pos = (pd.Series(work["timestamp"].to_numpy(), index=df.index)
                 .groupby(out["cluster_id"]).transform("idxmin"))
    out["is_cluster_anchor"] = first_pos.to_numpy() == df.index.to_numpy()
    return out


def summary(dedup: pd.DataFrame) -> dict:
    return {
        "total_records": int(len(dedup)),
        "estimated_unique_incidents": int(dedup["cluster_id"].nunique()),
        "merged_duplicates": int((dedup["dup_status"] == "merged duplicate").sum()),
        "possible_duplicates": int((dedup["dup_status"] == "possible duplicate").sum()),
    }
