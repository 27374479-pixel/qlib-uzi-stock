"""Fail-closed T05 readiness gate for source-grounded trend-state context."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_T05_CONTEXT_SOURCE_REVIEW.md"
T04_RESULT = ROOT / "V5_T04_RESULT.md"
T03_RESULT = ROOT / "V5_T03_RESULT.md"
T02_RESULT = ROOT / "V5_T02_RESULT.md"
OUT = ROOT / "output" / "v5_t05_context_source_readiness"
REPORT = OUT / "report.json"

REQUIRED = (
    "price_adjustment_basis",
    "ma20_direction_observable",
    "trend_up_predicate",
    "main_rise_predicate",
    "orderly_smooth_structure_representation",
    "base_definition",
    "wash_consolidation_exclusion",
    "ambiguous_structure_policy",
    "environment_theme_sentiment_safety_interfaces",
    "capital_character_representation",
    "state_conjunction_and_precedence",
    "causal_known_time",
    "t03_t04_handoff",
    "independent_validation_target",
    "upstream_lineage_binding",
)

CONTRACT = {
    "version": "V5_T05_CONTEXT_SOURCE_READINESS_V1",
    "mode": "SOURCE_READINESS_ONLY",
    "source_fixed": {
        "exclude_ma20_direction_down": True,
        "exclude_disordered_structure": True,
        "require_prior_base": True,
        "exclude_wash_or_consolidation_stage": True,
        "exclude_non_main_rise_stage": True,
        "participate_only_in_upward_trend": True,
        "participate_only_in_main_rise": True,
        "broader_context_required": True,
        "visual_45_degree_phrase_is_not_numeric_slope_rule": True,
        "isolated_ma20_rule_is_not_promoted_as_alpha": True,
    },
    "parameter_search": False,
    "trend_state_preregistration_authorized": False,
    "trend_return_screen_authorized": False,
    "t02_t03_t04_combination_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "price_adjustment_basis": {"ready": False, "detail": "source does not fix adjusted/raw price or corporate-action treatment"},
        "ma20_direction_observable": {"ready": False, "detail": "source excludes downward MA20 direction but does not define the exact direction comparison or tolerance"},
        "trend_up_predicate": {"ready": False, "detail": "source says only upward trend but does not define a deterministic trend predicate"},
        "main_rise_predicate": {"ready": False, "detail": "main-rise is required but not machine-defined"},
        "orderly_smooth_structure_representation": {"ready": False, "detail": "disordered charts are excluded and smooth names preferred, but no mechanical structure score is given"},
        "base_definition": {"ready": False, "detail": "a prior base is required but its lookback, geometry and causal completion rule are unspecified"},
        "wash_consolidation_exclusion": {"ready": False, "detail": "wash/consolidation stages are excluded without a deterministic state definition"},
        "ambiguous_structure_policy": {"ready": False, "detail": "the source rejects unreadable forms but does not define a machine ambiguity policy"},
        "environment_theme_sentiment_safety_interfaces": {"ready": False, "detail": "the source requires these contexts but provides no deterministic interfaces or mappings"},
        "capital_character_representation": {"ready": False, "detail": "capital character is named as context but not machine-defined"},
        "state_conjunction_and_precedence": {"ready": False, "detail": "source does not specify whether all conditions are mandatory or how conflicts are resolved"},
        "causal_known_time": {"ready": False, "detail": "earliest point-in-time timestamp at which the full state is known is unspecified"},
        "t03_t04_handoff": {"ready": False, "detail": "exact interface from prerequisite state into T03 daily entry context and T04 intraday position semantics is unresolved"},
        "independent_validation_target": {"ready": False, "detail": "no non-P&L label or source-complete target yet validates the operational state"},
        "upstream_lineage_binding": {"ready": True, "detail": "T05 binds frozen T02/T03/T04 results and its source review"},
        "literal_ma20_down_exclusion": {"ready": True, "detail": "source explicitly excludes stocks whose 20-session line points downward"},
        "literal_trend_and_main_rise_requirements": {"ready": True, "detail": "source explicitly says to participate only in upward trend and main-rise contexts"},
        "literal_broader_context_requirement": {"ready": True, "detail": "source explicitly requires environment/theme/sentiment/safety and related context rather than a single technical line"},
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
        "status": "READY_FOR_TREND_STATE_PREREGISTRATION" if ready else "DEFER_TREND_STATE_PREREGISTRATION",
        "ready": ready,
        "missing_fields": missing,
        "not_ready": not_ready,
        "trend_state_preregistration_authorized": ready,
        "trend_return_screen_authorized": False,
        "t02_t03_t04_combination_authorized": False,
        "effective_action": "WRITE_TREND_STATE_PREREGISTRATION" if ready else "SOURCE_AND_STATE_REPRESENTATION_ONLY",
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    for path in (SOURCE_REVIEW, T04_RESULT, T03_RESULT, T02_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)
    report = {
        "contract": CONTRACT,
        "lineage": {
            "source_review_sha256": sha256_file(SOURCE_REVIEW),
            "t04_result_sha256": sha256_file(T04_RESULT),
            "t03_result_sha256": sha256_file(T03_RESULT),
            "t02_result_sha256": sha256_file(T02_RESULT),
        },
        "evidence": evidence(),
    }
    report["decision"] = evaluate(report["evidence"])
    report["interpretation_boundary"] = (
        "T05 preserves the book's multi-condition trend/main-rise context while refusing to invent a numeric trend classifier or reuse isolated MA20 behavior as standalone alpha."
    )
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
