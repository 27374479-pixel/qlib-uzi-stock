"""Run the frozen X02 execution-validation chain locally in a fixed order.

This is orchestration only. It does not tune parameters or interpret results.
The runner fails fast and writes a manifest with stage status and output hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "x02_reproduction_20260912"
MANIFEST = OUT / "execution_validation_run_manifest.json"

STAGES = (
    ("minute_bar_structure", "audit_x02_minute_bar_structure.py"),
    ("legacy_reproduction", "reproduce_x02_local.py"),
    ("next_bar_execution", "audit_x02_next_bar_execution.py"),
    ("comparison", "compare_x02_next_bar_execution.py"),
)
EXPECTED_OUTPUTS = (
    "minute_bar_structure_audit.json",
    "report.json",
    "features.parquet",
    "next_bar_execution_audit.json",
    "next_bar_execution_comparison.json",
    "next_bar_execution_comparison.md",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--reuse-reproduction",
        action="store_true",
        help="reuse existing report.json/features.parquet but still rerun data-contract, next-bar and comparison audits",
    )
    return p.parse_args()


def build_plan(reuse_reproduction: bool = False) -> list[tuple[str, str]]:
    if not reuse_reproduction:
        return list(STAGES)
    return [stage for stage in STAGES if stage[0] != "legacy_reproduction"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_fingerprints(out: Path = OUT) -> dict[str, dict[str, object]]:
    result = {}
    for name in EXPECTED_OUTPUTS:
        path = out / name
        if path.exists():
            result[name] = {"exists": True, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        else:
            result[name] = {"exists": False, "bytes": None, "sha256": None}
    return result


def _write_manifest(payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    if args.reuse_reproduction:
        required = [OUT / "report.json", OUT / "features.parquet"]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise SystemExit(f"--reuse-reproduction requested but required artifacts are missing: {missing}")

    manifest = {
        "runner": "X02_EXECUTION_VALIDATION_CHAIN_V1",
        "parameter_search": False,
        "post_result_retuning_authorized": False,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "reuse_reproduction": bool(args.reuse_reproduction),
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
        if proc.returncode != 0:
            manifest["status"] = "FAILED"
            manifest["failed_stage"] = name
            manifest["artifacts"] = artifact_fingerprints()
            manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            _write_manifest(manifest)
            raise SystemExit(proc.returncode)

    manifest["status"] = "PASS"
    manifest["failed_stage"] = None
    manifest["artifacts"] = artifact_fingerprints()
    manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_manifest(manifest)
    print(f"\nPASS: {MANIFEST}", flush=True)


if __name__ == "__main__":
    main()
