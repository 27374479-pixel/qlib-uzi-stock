"""Fail-closed M02 readiness gate for market-cycle state mapping.

This module does not load market returns or fit a classifier.  It records which
pieces of the supplied-book -> M01-tape -> semantic-state chain are genuinely
specified before any strategy P&L can be consulted.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_M02_MARKET_CYCLE_SOURCE_REVIEW.md"
M01_SPEC = ROOT / "V5_M01_MARKET_TAPE_REPRESENTATION_SPEC.md"
M01_RESULT = ROOT / "V5_M01_RESULT.md"
OUT = ROOT / "output" / "v5_m02_market_cycle_source_readiness"
REPORT = OUT / "report.json"

REQUIRED = (
    "state_vocabulary",
    "observable_to_state_mapping",
    "threshold_or_boundary_basis",
    "lookback_and_persistence_rule",
    "transition_rule",
    "causal_decision_time",
    "independent_validation_target",
    "ambiguity_policy",
    "lineage_binding",
)

CONTRACT = {
    "version": "V5_M02_MARKET_CYCLE_SOURCE_READINESS_V1",
    "mode": "SOURCE_READINESS_ONLY",
    "upstream": "V5_M01_MARKET_TAPE_REPRESENTATION_V1",
    "required_for_classifier_preregistration": list(REQUIRED),
    "parameter_search": False,
    "classifier_preregistration_authorized": False,
    "return_screen_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "market_is_cyclical": {
            "ready": True,
            "detail": "source explicitly treats market conditions as cyclical and changing",
        },
        "deterioration_and_recovery_are_distinct": {
            "ready": True,
            "detail": "source qualitatively distinguishes decline/deterioration from recovery",
        },
        "market_tape_observables": {
            "ready": True,
            "detail": "source names daily market/tape review dimensions and M01 represents a conservative observable subset causally",
        },
        "m01_structural_representation": {
            "ready": True,
            "detail": "frozen M01 result is STRUCTURALLY_VALID_FOR_DESCRIPTIVE_MARKET_TAPE across 1,289 dates with zero invariant failures",
        },
        "state_vocabulary": {
            "ready": False,
            "detail": "reviewed passages use qualitative cycle language but do not define one exact finite machine state set",
        },
        "observable_to_state_mapping": {
            "ready": False,
            "detail": "source does not deterministically map M01 breadth/limit/board/prior-winner fields into semantic states",
        },
        "threshold_or_boundary_basis": {
            "ready": False,
            "detail": "no numeric source thresholds are given for bull/bear/recovery/retreat boundaries",
        },
        "lookback_and_persistence_rule": {
            "ready": False,
            "detail": "source does not specify a fixed completed-session lookback or state persistence rule",
        },
        "transition_rule": {
            "ready": False,
            "detail": "qualitative decline/recovery sequencing is not a deterministic transition function",
        },
        "causal_decision_time": {
            "ready": False,
            "detail": "source does not specify when an inferred market state becomes tradable relative to the close/open",
        },
        "independent_validation_target": {
            "ready": False,
            "detail": "no noncircular labelled target is supplied for falsifying the semantic state mapping independently of strategy returns",
        },
        "ambiguity_policy": {
            "ready": False,
            "detail": "source does not specify what state to assign when tape dimensions conflict",
        },
        "lineage_binding": {
            "ready": True,
            "detail": "M02 can bind the frozen M01 spec/result hashes before a future preregistration",
        },
    }


def evaluate(e: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing_fields = [field for field in REQUIRED if field not in e]
    not_ready = [
        {"field": field, "detail": e[field].get("detail")}
        for field in REQUIRED
        if field in e and not bool(e[field].get("ready"))
    ]
    ready = not missing_fields and not not_ready
    return {
        "status": (
            "READY_FOR_MARKET_CYCLE_CLASSIFIER_PREREGISTRATION"
            if ready
            else "DEFER_MARKET_CYCLE_CLASSIFIER_PREREGISTRATION"
        ),
        "ready": ready,
        "missing_fields": missing_fields,
        "not_ready": not_ready,
        "classifier_preregistration_authorized": ready,
        # Source readiness can only authorize writing a later preregistration.
        # It never directly authorizes a return screen or trading.
        "return_screen_authorized": False,
        "w01_return_screen_authorized": False,
        "effective_action": (
            "WRITE_SEPARATE_CLASSIFIER_PREREGISTRATION" if ready else "SOURCE_AND_INDEPENDENT_TARGET_RESEARCH_ONLY"
        ),
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    for path in (SOURCE_REVIEW, M01_SPEC, M01_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)

    e = evidence()
    decision = evaluate(e)
    report = {
        "contract": CONTRACT,
        "source_review_sha256": sha256_file(SOURCE_REVIEW),
        "upstream_lineage": {
            "m01_spec_sha256": sha256_file(M01_SPEC),
            "m01_result_sha256": sha256_file(M01_RESULT),
        },
        "evidence": e,
        "decision": decision,
        "interpretation_boundary": (
            "M01 makes the raw tape machine-ready; M02 asks whether the semantic state mapping is independently specified. "
            "A defer result forbids strategy-return threshold search and leaves W01 closed."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
