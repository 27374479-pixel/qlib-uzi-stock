#!/usr/bin/env python3
"""Freeze V4.18 event-cluster parameters from market-blind text labels only."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

FREEZE_VERSION = "v4.18-b.cluster-freeze.1"
THRESHOLD_GRID = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
MIN_DECISIVE = 200
MIN_POSITIVE = 40
MIN_NEGATIVE = 80
MIN_PRECISION = 0.90
BURN_IN_SESSIONS = 60
QUIET_RESET_SESSIONS = 20
VALID_LABELS = {"SAME_CONTEXT", "DIFFERENT_CONTEXT", "AMBIGUOUS"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--pairs", required=True, help="reviewed pair-audit CSV")
    p.add_argument("--audit-manifest", required=True)
    p.add_argument(
        "--output",
        default="output/v4_18_event_cluster_freeze_v1.json",
    )
    return p.parse_args()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def metrics_for_threshold(scores: pd.Series, truth: pd.Series, threshold: float) -> dict:
    pred = scores >= threshold
    positive = truth.eq("SAME_CONTEXT")
    negative = truth.eq("DIFFERENT_CONTEXT")
    tp = int((pred & positive).sum())
    fp = int((pred & negative).sum())
    fn = int((~pred & positive).sum())
    tn = int((~pred & negative).sum())
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "threshold": threshold,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def main() -> None:
    args = parse_args()
    pairs_path = Path(args.pairs)
    manifest_path = Path(args.audit_manifest)
    output_path = Path(args.output)

    if not pairs_path.exists() or not manifest_path.exists():
        raise SystemExit("reviewed pair CSV and audit manifest must both exist")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not bool(manifest.get("market_blind", False)):
        raise SystemExit("audit manifest is not marked market_blind=true")
    if bool(manifest.get("validation", {}).get("return_or_pnl_fields_read", True)):
        raise SystemExit("audit manifest indicates return/P&L fields may have been read")

    expected_pair_hash = str(manifest.get("pair_audit", {}).get("sha256", ""))
    current_pair_hash = sha256_file(pairs_path)
    # Review necessarily changes the CSV bytes by filling label/note columns.
    # The pre-review hash is provenance, not an equality gate after annotation.
    if not expected_pair_hash:
        raise SystemExit("audit manifest is missing the original pair-audit sha256")

    frame = pd.read_csv(pairs_path, dtype=str).fillna("")
    required = {"pair_id", "similarity", "pair_label"}
    missing = required - set(frame.columns)
    if missing:
        raise SystemExit(f"reviewed pair CSV missing columns: {sorted(missing)}")

    labels = frame["pair_label"].str.strip().str.upper()
    unexpected = sorted(set(labels) - VALID_LABELS - {""})
    if unexpected:
        raise SystemExit(f"unexpected pair labels: {unexpected}")

    reviewed = frame[labels.isin(VALID_LABELS)].copy()
    reviewed["pair_label"] = labels[labels.isin(VALID_LABELS)].values
    decisive = reviewed[reviewed["pair_label"].isin(["SAME_CONTEXT", "DIFFERENT_CONTEXT"])].copy()
    scores = pd.to_numeric(decisive["similarity"], errors="coerce")
    if scores.isna().any():
        raise SystemExit("decisive labels contain invalid similarity values")
    if ((scores < 0) | (scores > 1)).any():
        raise SystemExit("similarity values must be within [0,1]")

    positives = int(decisive["pair_label"].eq("SAME_CONTEXT").sum())
    negatives = int(decisive["pair_label"].eq("DIFFERENT_CONTEXT").sum())
    ambiguous = int(reviewed["pair_label"].eq("AMBIGUOUS").sum())

    failures = []
    if len(decisive) < MIN_DECISIVE:
        failures.append(f"decisive labels {len(decisive)} < {MIN_DECISIVE}")
    if positives < MIN_POSITIVE:
        failures.append(f"SAME_CONTEXT labels {positives} < {MIN_POSITIVE}")
    if negatives < MIN_NEGATIVE:
        failures.append(f"DIFFERENT_CONTEXT labels {negatives} < {MIN_NEGATIVE}")
    if failures:
        raise SystemExit("text calibration evidence insufficient: " + "; ".join(failures))

    evaluations = [
        metrics_for_threshold(scores, decisive["pair_label"], threshold)
        for threshold in THRESHOLD_GRID
    ]
    eligible = [m for m in evaluations if m["precision"] >= MIN_PRECISION]
    if not eligible:
        table = "; ".join(
            f"{m['threshold']:.2f}:P={m['precision']:.3f},R={m['recall']:.3f}"
            for m in evaluations
        )
        raise SystemExit(
            "no preregistered threshold reaches precision >= "
            f"{MIN_PRECISION:.2f}; text representation/theme eligibility must be improved "
            f"without return data. metrics={table}"
        )

    # Primary rule: maximize recall subject to precision floor.  Deterministic
    # tie-breakers prefer higher precision and then the stricter threshold.
    selected = sorted(
        eligible,
        key=lambda m: (m["recall"], m["precision"], m["threshold"]),
        reverse=True,
    )[0]

    freeze = {
        "cluster_config_version": FREEZE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scientific_status": "TEXT_ONLY_CALIBRATION_FROZEN_NOT_PERFORMANCE_TESTED",
        "market_blind": True,
        "x02_returns_read": False,
        "text_feature_version": manifest.get("text_feature_version"),
        "similarity_metric": manifest.get("similarity_metric"),
        "similarity_threshold": selected["threshold"],
        "threshold_grid": THRESHOLD_GRID,
        "selection_rule": {
            "minimum_precision": MIN_PRECISION,
            "objective": "maximize recall subject to precision floor",
            "tie_breakers": ["higher precision", "higher threshold"],
        },
        "selected_metrics": selected,
        "all_threshold_metrics": evaluations,
        "text_audit": {
            "original_manifest": str(manifest_path),
            "original_unreviewed_pair_sha256": expected_pair_hash,
            "reviewed_pair_sha256": current_pair_hash,
            "decisive_pair_count": int(len(decisive)),
            "positive_label_count": positives,
            "negative_label_count": negatives,
            "ambiguous_label_count": ambiguous,
        },
        "calendar_sha256": manifest.get("calendar", {}).get("calendar_sha256"),
        "lifecycle": {
            "research_start_burn_in_sessions": BURN_IN_SESSIONS,
            "quiet_reset_sessions": QUIET_RESET_SESSIONS,
            "same_day_batching_required": True,
            "retroactive_existing_cluster_merge_allowed": False,
        },
        "validation": {
            "pass": True,
            "minimum_label_counts_met": True,
            "minimum_precision_met": True,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(freeze, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(freeze, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
