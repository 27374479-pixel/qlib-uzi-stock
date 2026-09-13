"""Freeze the forward paper-trial contract for X02 after execution validation.

This stage never authorizes live trading. It only materializes a fixed forward
paper-trial contract when the pre-registered execution gate says paper trading
is allowed. Historical uncertainty/stability diagnostics are required to be
lineage-valid but do not change the gate threshold.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "x02_reproduction_20260912"
REPORT = OUT / "report.json"
GATE = OUT / "execution_gate.json"
UNCERTAINTY = OUT / "execution_uncertainty.json"
STABILITY = OUT / "execution_stability.json"
ARTIFACT_MANIFEST = OUT / "execution_artifact_manifest.json"
OUTPUT_CONTRACT = OUT / "paper_trial_contract.json"
OUTPUT_READINESS = OUT / "paper_trial_readiness.json"

EXPECTED_LEGACY_CONTRACT = {
    "signal": "existing X02",
    "top_n": 3,
    "rank": "clean_mom20_rank",
    "entry": "14:45 close",
    "exit": "next session 10:00",
    "limit_buffer": 0.005,
}

PAPER_TRIAL_CONTRACT = {
    "contract": "X02_FORWARD_PAPER_TRIAL_V1",
    "purpose": "prospective paper-trading observation only",
    "live_trading_authorized": False,
    "parameter_search_authorized": False,
    "post_start_retuning_authorized": False,
    "strategy": {
        "signal": "existing X02",
        "market_gate": "breadth5 > 0 and money_effect > 0",
        "rank": "clean_mom20_rank descending",
        "top_n": 3,
        "underfilled_day_policy": "all cash when fewer than 3 eligible names exist",
        "universe_note": "inherit frozen X02 universe; ChiNext included and STAR excluded",
    },
    "decision_and_execution": {
        "decision_cutoff": "persisted 5m record labelled 14:45 close",
        "paper_entry": "open of next persisted 5m record labelled 14:50",
        "vendor_label_semantics": "must remain consistent with the validated minute-bar structure audit",
        "limit_buffer": 0.005,
        "liquidity_check": "positive next-record volume and amount",
        "failed_fill_policy": "slot remains cash; no replacement and no reweighting",
        "paper_exit": "next session persisted 5m record labelled 10:00 close",
        "cost_model": "CONSERVATIVE engine cost schedule",
    },
    "forward_observation": {
        "start_rule": "first eligible trading session after a READY_FOR_FORWARD_PAPER_TRIAL readiness artifact is created",
        "minimum_trading_sessions": 126,
        "descriptive_checkpoints_trading_sessions": [21, 63, 126],
        "early_stop_for_performance": False,
        "required_metrics": [
            "net_return",
            "corrected_max_drawdown",
            "fill_rate",
            "cash_slots",
            "entry_slippage_vs_1445",
            "active_selection_days",
        ],
    },
    "interpretation_boundary": (
        "A positive forward paper trial would still not authorize live capital automatically; "
        "a separate decision and risk review is required after the predeclared observation period."
    ),
}


def canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_legacy_contract(report: dict[str, Any]) -> list[str]:
    contract = report.get("contract") or {}
    failures: list[str] = []
    for key, expected in EXPECTED_LEGACY_CONTRACT.items():
        if contract.get(key) != expected:
            failures.append(f"legacy reproduction contract mismatch for {key}: {contract.get(key)!r} != {expected!r}")
    return failures


def build_readiness(
    report: dict[str, Any],
    gate: dict[str, Any],
    uncertainty: dict[str, Any],
    stability: dict[str, Any],
    artifact_manifest: dict[str, Any],
) -> dict[str, Any]:
    reasons = validate_legacy_contract(report)
    if not bool(artifact_manifest.get("pass")):
        reasons.append("execution artifact manifest did not pass")
    if not bool((uncertainty.get("lineage") or {}).get("pass")):
        reasons.append("execution uncertainty lineage did not pass")
    if not bool((stability.get("lineage") or {}).get("pass")):
        reasons.append("execution stability lineage did not pass")
    if not bool((uncertainty.get("cagr_reconciliation") or {}).get("pass")):
        reasons.append("uncertainty observed CAGR did not reconcile to the execution audit")

    gate_status = gate.get("status")
    gate_authorized = bool(gate.get("paper_trading_authorized"))
    if gate_status != "PROVISIONALLY_ROBUST_FOR_PAPER_TRADING_ONLY" or not gate_authorized:
        reasons.append("pre-registered execution gate does not authorize forward paper trading")

    ready = not reasons
    return {
        "readiness": "X02_FORWARD_PAPER_TRIAL_READINESS_V1",
        "status": "READY_FOR_FORWARD_PAPER_TRIAL" if ready else "NOT_AUTHORIZED_FOR_FORWARD_PAPER_TRIAL",
        "ready": ready,
        "paper_trading_authorized": ready,
        "live_trading_authorized": False,
        "parameter_search_authorized": False,
        "post_start_retuning_authorized": False,
        "gate_status": gate_status,
        "paper_trial_contract_sha256": canonical_sha256(PAPER_TRIAL_CONTRACT),
        "reasons": reasons if reasons else ["execution gate and all required lineage checks passed"],
        "interpretation_boundary": (
            "Readiness starts a frozen prospective paper trial only. It does not turn historical evidence into pristine OOS evidence and does not authorize live capital."
        ),
    }


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"missing required input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    report = _load(REPORT)
    gate = _load(GATE)
    uncertainty = _load(UNCERTAINTY)
    stability = _load(STABILITY)
    artifact_manifest = _load(ARTIFACT_MANIFEST)

    contract_payload = dict(PAPER_TRIAL_CONTRACT)
    contract_payload["source_lineage"] = {
        "report_sha256": sha256_file(REPORT),
        "execution_gate_sha256": sha256_file(GATE),
        "execution_uncertainty_sha256": sha256_file(UNCERTAINTY),
        "execution_stability_sha256": sha256_file(STABILITY),
        "execution_artifact_manifest_sha256": sha256_file(ARTIFACT_MANIFEST),
    }
    OUTPUT_CONTRACT.write_text(json.dumps(contract_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    readiness = build_readiness(report, gate, uncertainty, stability, artifact_manifest)
    readiness["paper_trial_contract_file_sha256"] = sha256_file(OUTPUT_CONTRACT)
    OUTPUT_READINESS.write_text(json.dumps(readiness, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(readiness, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
