"""Run the frozen X02 execution-validation chain locally in a fixed order.

This is orchestration only. It does not tune parameters. The final historical
gate can at most unlock a frozen forward paper trial; neither the gate nor the
runner authorizes live trading. The runner fails fast and records hashes.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from x02_provenance import SELECTION_FILES, file_fingerprint, validate_reproduction_artifacts

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "x02_reproduction_20260912"
MANIFEST = OUT / "execution_validation_run_manifest.json"
ENGINE = ROOT / "v4_3_long_only_portfolio.py"

STAGES = (
    ("minute_bar_structure", "audit_x02_minute_bar_structure.py"),
    ("legacy_reproduction", "reproduce_x02_local.py"),
    ("next_bar_execution", "audit_x02_next_bar_execution.py"),
    ("execution_artifact_binding", "bind_x02_execution_artifacts.py"),
    ("comparison", "compare_x02_next_bar_execution.py"),
    ("execution_uncertainty", "analyze_x02_execution_uncertainty.py"),
    ("execution_stability", "analyze_x02_execution_stability.py"),
    ("execution_gate", "evaluate_x02_execution_gate.py"),
    ("paper_trial_readiness", "prepare_x02_paper_trial.py"),
)
EXPECTED_OUTPUTS = (
    "minute_bar_structure_audit.json",
    "report.json",
    "features.parquet",
    *SELECTION_FILES.values(),
    "next_bar_execution_audit.json",
    "execution_artifact_manifest.json",
    "next_bar_execution_comparison.json",
    "next_bar_execution_comparison.md",
    "execution_uncertainty.json",
    "execution_uncertainty.md",
    "execution_stability.json",
    "execution_stability.md",
    "execution_gate.json",
    "execution_gate.md",
    "paper_trial_contract.json",
    "paper_trial_readiness.json",
)
SOURCE_FILES = (
    "audit_x02_minute_bar_structure.py",
    "reproduce_x02_local.py",
    "audit_x02_next_bar_execution.py",
    "bind_x02_execution_artifacts.py",
    "compare_x02_next_bar_execution.py",
    "analyze_x02_execution_uncertainty.py",
    "analyze_x02_execution_uncertainty_v2.py",
    "analyze_x02_execution_stability.py",
    "evaluate_x02_execution_gate.py",
    "prepare_x02_paper_trial.py",
    "x02_provenance.py",
    "v4_3_long_only_portfolio.py",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--reuse-reproduction",
        action="store_true",
        help=(
            "reuse report/features/frozen-selection artifacts only when all recorded hashes "
            "match the current engine and exact local files"
        ),
    )
    return p.parse_args()


def build_plan(reuse_reproduction: bool = False) -> list[tuple[str, str]]:
    if not reuse_reproduction:
        return list(STAGES)
    return [stage for stage in STAGES if stage[0] != "legacy_reproduction"]


def artifact_fingerprints(out: Path = OUT) -> dict[str, dict[str, object]]:
    return {name: file_fingerprint(out / name) for name in EXPECTED_OUTPUTS}


def source_fingerprints(root: Path = ROOT) -> dict[str, dict[str, object]]:
    return {name: file_fingerprint(root / name) for name in SOURCE_FILES}


def _write_manifest(payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    reuse_validation = None
    if args.reuse_reproduction:
        reuse_validation = validate_reproduction_artifacts(OUT, ENGINE)
        if not reuse_validation["pass"]:
            raise SystemExit(
                "--reuse-reproduction rejected: " + "; ".join(reuse_validation["failures"])
            )

    manifest = {
        "runner": "X02_EXECUTION_VALIDATION_CHAIN_V7",
        "parameter_search": False,
        "post_result_retuning_authorized": False,
        "live_trading_authorized": False,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "reuse_reproduction": bool(args.reuse_reproduction),
        "reuse_validation": reuse_validation,
        "sources": source_fingerprints(),
        "stages": [],
        "status": "RUNNING",
    }
    _write_manifest(manifest)

    for name, script in build_plan(args.reuse_reproduction):
        started = datetime.now(timezone.utc).isoformat()
        print(f"\n=== {name}: {script} ===", flush=True)
        proc = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, check=False)
        record = {
            "name": name,
            "script": script,
            "started_at_utc": started,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "returncode": int(proc.returncode),
        }
        manifest["stages"].append(record)
        manifest["artifacts"] = artifact_fingerprints()
        if proc.returncode != 0:
            manifest["status"] = "FAILED"
            manifest["failed_stage"] = name
            manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            _write_manifest(manifest)
            raise SystemExit(proc.returncode)
        _write_manifest(manifest)

    final_lineage = validate_reproduction_artifacts(OUT, ENGINE)
    if not final_lineage["pass"]:
        manifest["status"] = "FAILED"
        manifest["failed_stage"] = "final_lineage_validation"
        manifest["final_lineage"] = final_lineage
        manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_manifest(manifest)
        raise SystemExit("final reproduction lineage validation failed")

    manifest["status"] = "PASS"
    manifest["failed_stage"] = None
    manifest["final_lineage"] = final_lineage
    manifest["artifacts"] = artifact_fingerprints()
    for name, filename in (
        ("execution_gate", "execution_gate.json"),
        ("execution_uncertainty", "execution_uncertainty.json"),
        ("execution_stability", "execution_stability.json"),
        ("paper_trial_readiness", "paper_trial_readiness.json"),
    ):
        path = OUT / filename
        if path.exists():
            manifest[name] = json.loads(path.read_text(encoding="utf-8"))
    manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_manifest(manifest)
    print(f"\nPASS: {MANIFEST}", flush=True)


if __name__ == "__main__":
    main()
