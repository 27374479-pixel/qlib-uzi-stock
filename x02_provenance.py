"""Provenance helpers for the frozen X02 local validation chain."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SELECTION_FILES = {
    "original_gate": "original_gate_selected.parquet",
    "no_market_gate": "no_market_gate_selected.parquet",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_fingerprint(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"exists": False, "bytes": None, "sha256": None}
    return {"exists": True, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_reproduction_artifacts(out: Path, engine_path: Path) -> dict[str, object]:
    report_path = out / "report.json"
    features_path = out / "features.parquet"
    failures: list[str] = []
    for path in (report_path, features_path, engine_path):
        if not path.exists():
            failures.append(f"missing {path}")
    for filename in SELECTION_FILES.values():
        path = out / filename
        if not path.exists():
            failures.append(f"missing {path}")
    if failures:
        return {"pass": False, "failures": failures}

    report = load_json(report_path)
    actual_engine = sha256_file(engine_path)
    actual_features = sha256_file(features_path)
    expected_engine = report.get("engine_sha256")
    expected_features = report.get("features_sha256")

    if not expected_engine:
        failures.append("report.json lacks engine_sha256")
    elif str(expected_engine) != actual_engine:
        failures.append("report engine_sha256 does not match current engine file")
    if not expected_features:
        failures.append("report.json lacks features_sha256; rerun reproduce_x02_local.py once")
    elif str(expected_features) != actual_features:
        failures.append("report features_sha256 does not match current features.parquet")

    selection_artifacts = report.get("selection_artifacts") or {}
    actual_selection_hashes: dict[str, str] = {}
    for variant, filename in SELECTION_FILES.items():
        path = out / filename
        actual_hash = sha256_file(path)
        actual_selection_hashes[variant] = actual_hash
        metadata = selection_artifacts.get(variant) or {}
        if metadata.get("filename") != filename:
            failures.append(f"selection artifact filename mismatch for {variant}")
        expected_hash = metadata.get("sha256")
        if not expected_hash:
            failures.append(f"report.json lacks selection hash for {variant}; rerun reproduce_x02_local.py once")
        elif str(expected_hash) != actual_hash:
            failures.append(f"selection artifact hash mismatch for {variant}")

    contract = report.get("contract", {})
    expected_contract = {
        "top_n": 3,
        "rank": "clean_mom20_rank",
        "entry": "14:45 close",
        "exit": "next session 10:00",
        "limit_buffer": 0.005,
        "parameter_search": False,
        "announcements_used": False,
    }
    for key, expected in expected_contract.items():
        if contract.get(key) != expected:
            failures.append(f"frozen contract mismatch for {key}")

    return {
        "pass": not failures,
        "failures": failures,
        "report_sha256": sha256_file(report_path),
        "features_sha256": actual_features,
        "engine_sha256": actual_engine,
        "selection_sha256": actual_selection_hashes,
    }


def require_reproduction_artifacts(out: Path, engine_path: Path) -> dict[str, object]:
    result = validate_reproduction_artifacts(out, engine_path)
    if not result["pass"]:
        raise RuntimeError("reproduction lineage validation failed: " + "; ".join(result["failures"]))
    return result
