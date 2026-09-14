"""M03 source-grounded market-cycle ontology gate.

This module freezes a semantic vocabulary only. It does not classify dates,
load strategy returns, or fit thresholds.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_M03_MARKET_CYCLE_ONTOLOGY_SOURCE_REVIEW.md"
M02_RESULT = ROOT / "V5_M02_RESULT.md"
M01_RESULT = ROOT / "V5_M01_RESULT.md"
OUT = ROOT / "output" / "v5_m03_market_cycle_ontology"
REPORT = OUT / "report.json"

SOURCE_STATES = (
    "BEAR_DECLINE_CONTEXT",
    "BEAR_RECOVERY_CONTEXT",
    "BULL_BROADENING_CONTEXT",
)
SYSTEM_FALLBACK = "UNKNOWN"

CONTRACT = {
    "version": "V5_M03_MARKET_CYCLE_ONTOLOGY_V1",
    "mode": "SOURCE_ONTOLOGY_ONLY",
    "source_states": list(SOURCE_STATES),
    "system_fallback": SYSTEM_FALLBACK,
    "source_supported_partial_transitions": [
        ["BEAR_DECLINE_CONTEXT", "BEAR_RECOVERY_CONTEXT"],
    ],
    "bull_bear_cycle_is_qualitatively_supported": True,
    "date_classification_authorized": False,
    "observable_to_state_mapping_authorized": False,
    "threshold_search_authorized": False,
    "return_screen_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}

REQUIRED_FOR_MAPPING_PREREGISTRATION = (
    "observable_to_state_mapping",
    "boundary_basis",
    "lookback_and_persistence",
    "transition_confirmation",
    "causal_decision_time",
    "ambiguity_policy",
    "independent_validation_target",
    "lineage_binding",
)


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "state_vocabulary": {
            "ready": True,
            "detail": "stronger source extraction supports bear-decline, bear-recovery and broad bull contexts; UNKNOWN remains a system fallback",
        },
        "partial_transition_semantics": {
            "ready": True,
            "detail": "source supports decline -> recovery conceptually and longer-horizon bull/bear cycling",
        },
        "observable_to_state_mapping": {
            "ready": False,
            "detail": "source does not deterministically map M01 tape fields to the frozen states",
        },
        "boundary_basis": {
            "ready": False,
            "detail": "no numeric/source-complete boundaries are supplied for the state transitions",
        },
        "lookback_and_persistence": {
            "ready": False,
            "detail": "source does not define how many completed sessions establish/persist a state",
        },
        "transition_confirmation": {
            "ready": False,
            "detail": "qualitative progression is supported but exact confirmation rules are not",
        },
        "causal_decision_time": {
            "ready": False,
            "detail": "earliest tradable timestamp after state recognition is unspecified",
        },
        "ambiguity_policy": {
            "ready": True,
            "detail": "architecture fails closed to UNKNOWN when source-grounded state assignment is not defensible",
        },
        "independent_validation_target": {
            "ready": False,
            "detail": "no non-strategy-return target yet exists to validate date-level state assignments",
        },
        "lineage_binding": {
            "ready": True,
            "detail": "M03 binds frozen M01/M02 results and its own source review",
        },
    }


def evaluate(e: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [k for k in REQUIRED_FOR_MAPPING_PREREGISTRATION if k not in e]
    not_ready = [
        {"field": k, "detail": e[k].get("detail")}
        for k in REQUIRED_FOR_MAPPING_PREREGISTRATION
        if k in e and not bool(e[k].get("ready"))
    ]
    mapping_ready = not missing and not not_ready
    return {
        "status": "READY_FOR_MAPPING_PREREGISTRATION" if mapping_ready else "ONTOLOGY_READY_MAPPING_DEFERRED",
        "ontology_ready": bool(e.get("state_vocabulary", {}).get("ready")),
        "mapping_ready": mapping_ready,
        "missing_fields": missing,
        "not_ready": not_ready,
        "mapping_preregistration_authorized": mapping_ready,
        "date_classification_authorized": False,
        "return_screen_authorized": False,
        "w01_return_screen_authorized": False,
        "effective_action": "WRITE_SEPARATE_MAPPING_PREREGISTRATION" if mapping_ready else "SOURCE_AND_INDEPENDENT_MAPPING_RESEARCH_ONLY",
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    for path in (SOURCE_REVIEW, M02_RESULT, M01_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)

    e = evidence()
    decision = evaluate(e)
    report = {
        "contract": CONTRACT,
        "lineage": {
            "source_review_sha256": sha256_file(SOURCE_REVIEW),
            "m02_result_sha256": sha256_file(M02_RESULT),
            "m01_result_sha256": sha256_file(M01_RESULT),
        },
        "evidence": e,
        "decision": decision,
        "interpretation_boundary": (
            "M03 freezes a source-grounded semantic vocabulary only. It does not assign historical dates to states and may not use X02/W01 P&L to create the missing mapping."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
