"""Fail-closed W05 readiness gate for W01 rebound-context / prior-high semantics."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_W05_REBOUND_CONTEXT_SOURCE_REVIEW.md"
W04_RESULT = ROOT / "V5_W04_RESULT.md"
W03_RESULT = ROOT / "V5_W03_RESULT.md"
W02_RESULT = ROOT / "V5_W02_RESULT.md"
M02_RESULT = ROOT / "V5_M02_RESULT.md"
LEDGER = ROOT / "V5_BOOK_EVIDENCE_LEDGER.md"
OUT = ROOT / "output" / "v5_w05_rebound_context_source_readiness"
REPORT = OUT / "report.json"

REQUIRED = (
    "rebound_scope",
    "rebound_reference_series",
    "rebound_start_anchor",
    "rebound_end_anchor",
    "rebound_magnitude_rule",
    "rebound_duration_rule",
    "rebound_known_time",
    "rebound_to_leader_top_relation",
    "prior_high_reference",
    "prior_high_near_definition",
    "post_entry_target_role",
    "new_high_after_entry_rule",
    "independent_validation_or_source_basis",
    "upstream_lineage_binding",
)

CONTRACT = {
    "version": "V5_W05_REBOUND_CONTEXT_SOURCE_READINESS_V1",
    "mode": "SOURCE_READINESS_ONLY",
    "source_fixed": {
        "sequence": [
            "bear_market_context",
            "large_rebound",
            "leader_top",
            "first_post_top_left_side_opportunity",
            "approx_3_to_7_sessions_and_20_to_25_percent_decline",
            "possible_rebound_toward_prior_high_area",
        ],
        "drawdown_window_trading_sessions_approx": [3, 7],
        "drawdown_fraction_approx": [0.20, 0.25],
        "prior_high_area_is_descriptive_not_exit_rule": True,
    },
    "semantic_guard": "large rebound is not silently redefined as a stock-specific prior wave",
    "parameter_search": False,
    "rebound_context_preregistration_authorized": False,
    "w01_event_preregistration_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "rebound_scope": {
            "ready": False,
            "detail": "source says large rebound but does not machine-define market/index/theme/stock scope",
        },
        "rebound_reference_series": {
            "ready": False,
            "detail": "no exact point-in-time index, market basket, theme series or stock series is specified",
        },
        "rebound_start_anchor": {
            "ready": False,
            "detail": "source does not define the causal start anchor of the large rebound",
        },
        "rebound_end_anchor": {
            "ready": False,
            "detail": "source does not define when the large rebound ends without future-looking labelling",
        },
        "rebound_magnitude_rule": {
            "ready": False,
            "detail": "the adjective large has no numeric magnitude rule in the reviewed passage",
        },
        "rebound_duration_rule": {
            "ready": False,
            "detail": "the reviewed passage does not specify a fixed duration for the preceding large rebound",
        },
        "rebound_known_time": {
            "ready": False,
            "detail": "earliest causal timestamp when large-rebound completion is known is unspecified",
        },
        "rebound_to_leader_top_relation": {
            "ready": False,
            "detail": "source gives ordering language but not a deterministic overlap/gap relation between rebound end and leader top",
        },
        "prior_high_reference": {
            "ready": False,
            "detail": "source says prior high area but does not identify which historical high or price field",
        },
        "prior_high_near_definition": {
            "ready": False,
            "detail": "the qualitative word near has no source-fixed numerical tolerance",
        },
        "post_entry_target_role": {
            "ready": False,
            "detail": "source describes a common rebound outcome but does not state that prior-high proximity is an executable exit rule",
        },
        "new_high_after_entry_rule": {
            "ready": False,
            "detail": "source notes stronger cases can make new highs but gives no causal exit/reassessment rule for that branch",
        },
        "independent_validation_or_source_basis": {
            "ready": False,
            "detail": "no non-P&L basis yet resolves rebound scope/anchors/magnitude or prior-high target semantics",
        },
        "upstream_lineage_binding": {
            "ready": True,
            "detail": "W05 can bind frozen M02/W02/W03/W04 results, its source review and the evidence ledger",
        },
        "literal_bear_context": {
            "ready": True,
            "detail": "primary source explicitly places the setup in bear-market context",
        },
        "literal_large_rebound_precedes_top": {
            "ready": True,
            "detail": "primary source explicitly places a large rebound before the leader-top setup at a qualitative level",
        },
        "literal_prior_high_area_outcome": {
            "ready": True,
            "detail": "primary source describes a possible quick rebound toward the prior-high area after the left-side opportunity",
        },
    }


def evaluate(e: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [field for field in REQUIRED if field not in e]
    not_ready = [
        {"field": field, "detail": e[field].get("detail")}
        for field in REQUIRED
        if field in e and not bool(e[field].get("ready"))
    ]
    ready = not missing and not not_ready
    return {
        "status": (
            "READY_FOR_REBOUND_CONTEXT_PREREGISTRATION"
            if ready
            else "DEFER_REBOUND_CONTEXT_PREREGISTRATION"
        ),
        "ready": ready,
        "missing_fields": missing,
        "not_ready": not_ready,
        "rebound_context_preregistration_authorized": ready,
        # A source-readiness pass could only authorize another preregistration.
        "w01_event_preregistration_authorized": False,
        "w01_return_screen_authorized": False,
        "effective_action": (
            "WRITE_SEPARATE_REBOUND_CONTEXT_PREREGISTRATION"
            if ready
            else "SOURCE_AND_REPRESENTATION_RESEARCH_ONLY"
        ),
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    for path in (SOURCE_REVIEW, W04_RESULT, W03_RESULT, W02_RESULT, M02_RESULT, LEDGER):
        if not path.exists():
            raise FileNotFoundError(path)

    report = {
        "contract": CONTRACT,
        "lineage": {
            "source_review_sha256": sha256_file(SOURCE_REVIEW),
            "w04_result_sha256": sha256_file(W04_RESULT),
            "w03_result_sha256": sha256_file(W03_RESULT),
            "w02_result_sha256": sha256_file(W02_RESULT),
            "m02_result_sha256": sha256_file(M02_RESULT),
            "evidence_ledger_sha256": sha256_file(LEDGER),
        },
        "evidence": evidence(),
    }
    report["decision"] = evaluate(report["evidence"])
    report["interpretation_boundary"] = (
        "W05 preserves the source's qualitative large-rebound-before-leader-top ordering and prior-high-area "
        "post-entry description, but does not invent rebound scope, magnitude, anchors, target tolerance or exit rules from P&L."
    )
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
