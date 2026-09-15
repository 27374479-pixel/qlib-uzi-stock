"""Fail-closed source-readiness gate for the M07 two-stage recovery ontology."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_M07_RECOVERY_LEADERSHIP_SEQUENCE_REVIEW.md"
M06_RESULT = ROOT / "V5_M06_RESULT.md"
M05_RESULT = ROOT / "V5_M05_RESULT.md"
OUT = ROOT / "output" / "v5_m07_recovery_leadership_sequence"
REPORT = OUT / "report.json"

REQUIRED_FOR_NEXT_PREREG = (
    "source_based_observable_assignment",
    "causal_known_time",
    "stage_coexistence_policy",
    "transition_lag_structure",
    "independent_non_pnl_validation_target",
    "ambiguity_policy",
    "lineage_binding",
)

CONTRACT = {
    "version": "V5_M07_RECOVERY_LEADERSHIP_SEQUENCE_V1",
    "mode": "SOURCE_ONTOLOGY_ONLY",
    "semantic_order": ["RECOVERY_ONSET_CONTEXT", "LEADERSHIP_EMERGENCE_CONTEXT"],
    "m06_rescue_authorized": False,
    "historical_state_labels_authorized": False,
    "strategy_returns_used": False,
    "parameter_search": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "source_supports_recovery_onset": {
            "ready": True,
            "detail": "book says bear-market opportunity appears when deterioration settles and recovery starts",
        },
        "source_supports_later_strong_stock_emergence": {
            "ready": True,
            "detail": "same source passage says new strong stocks often appear after a decline wave and describes bear markets as stage-by-stage",
        },
        "semantic_order": {
            "ready": True,
            "detail": "source sequence supports onset before leadership emergence as distinct concepts",
        },
        "source_based_observable_assignment": {
            "ready": False,
            "detail": "source does not machine-map M01/M04/M05 fields into the two stages",
        },
        "causal_known_time": {
            "ready": False,
            "detail": "exact completed-close/open handoff for either stage is unresolved",
        },
        "stage_coexistence_policy": {
            "ready": False,
            "detail": "source does not say whether onset and leadership may coexist on the same session",
        },
        "transition_lag_structure": {
            "ready": False,
            "detail": "source gives ordering but no numeric lag or persistence rule",
        },
        "independent_non_pnl_validation_target": {
            "ready": False,
            "detail": "a separate non-strategy target must be preregistered before quantitative stage validation",
        },
        "ambiguity_policy": {
            "ready": False,
            "detail": "conflicting broad-market and leadership evidence has no source-defined resolution",
        },
        "lineage_binding": {
            "ready": True,
            "detail": "M07 can bind M05 representation and M06 frozen failure exactly",
        },
    }


def evaluate(e: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_FOR_NEXT_PREREG if field not in e]
    unresolved = [
        {"field": field, "detail": e[field].get("detail")}
        for field in REQUIRED_FOR_NEXT_PREREG
        if field in e and not bool(e[field].get("ready"))
    ]
    next_ready = not missing and not unresolved
    return {
        "status": "READY_FOR_TWO_STAGE_VALIDATION_PREREGISTRATION" if next_ready else "ONTOLOGY_READY_TWO_STAGE_MAPPING_DEFERRED",
        "ontology_ready": True,
        "quantitative_mapping_ready": next_ready,
        "missing_fields": missing,
        "unresolved": unresolved,
        "effective_action": "WRITE_SEPARATE_NON_PNL_STAGE_VALIDATION_PREREGISTRATION" if next_ready else "SOURCE_AND_MAPPING_RESEARCH_ONLY",
        "historical_state_labels_authorized": False,
        "w01_return_screen_authorized": False,
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    for path in (SOURCE_REVIEW, M06_RESULT, M05_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)
    e = evidence()
    report = {
        "contract": CONTRACT,
        "lineage": {
            "source_review_sha256": sha256_file(SOURCE_REVIEW),
            "m06_result_sha256": sha256_file(M06_RESULT),
            "m05_result_sha256": sha256_file(M05_RESULT),
        },
        "evidence": e,
        "decision": evaluate(e),
        "interpretation_boundary": (
            "M07 freezes only source-supported stage semantics and order. It does not assign historical dates or use M06 loadings to define a new model."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
