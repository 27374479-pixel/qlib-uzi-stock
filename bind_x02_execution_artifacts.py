"""Bind X02 next-record execution CSV artifacts to the audit report by SHA-256."""
from __future__ import annotations

import json
from pathlib import Path

from x02_provenance import file_fingerprint, sha256_file

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "x02_reproduction_20260912"
AUDIT = OUT / "next_bar_execution_audit.json"
OUTPUT = OUT / "execution_artifact_manifest.json"
VARIANTS = ("original_gate", "no_market_gate")
COSTS = ("BASE", "CONSERVATIVE")


def expected_execution_files() -> tuple[str, ...]:
    names: list[str] = []
    for variant in VARIANTS:
        for cost in COSTS:
            key = f"{variant}_{cost}"
            names.extend((f"{key}_next_bar_ledger.csv", f"{key}_next_bar_daily.csv"))
    return tuple(names)


def build_manifest(out: Path = OUT, audit_path: Path = AUDIT) -> dict:
    failures: list[str] = []
    if not audit_path.exists():
        return {"pass": False, "failures": [f"missing {audit_path}"], "artifacts": {}}
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if not bool((audit.get("inputs") or {}).get("pass")):
        failures.append("next-record audit input lineage did not pass")

    artifacts = {name: file_fingerprint(out / name) for name in expected_execution_files()}
    for name, meta in artifacts.items():
        if not meta["exists"]:
            failures.append(f"missing execution artifact {name}")

    return {
        "manifest": "X02_EXECUTION_ARTIFACT_MANIFEST_V1",
        "pass": not failures,
        "failures": failures,
        "audit_sha256": sha256_file(audit_path),
        "artifacts": artifacts,
        "interpretation_boundary": "This manifest binds execution outputs only; it does not validate strategy profitability.",
    }


def main() -> None:
    manifest = build_manifest()
    OUTPUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if not manifest["pass"]:
        raise SystemExit("execution artifact binding failed")


if __name__ == "__main__":
    main()
