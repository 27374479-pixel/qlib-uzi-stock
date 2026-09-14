"""Fail-closed T04 readiness gate for source-grounded low-buy intraday semantics."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_T04_LOW_BUY_POSITION_SOURCE_REVIEW.md"
T03_RESULT = ROOT / "V5_T03_RESULT.md"
OUT = ROOT / "output" / "v5_t04_low_buy_position_source_readiness"
REPORT = OUT / "report.json"

REQUIRED = (
    "intraday_reference_window",
    "intraday_data_source_and_frequency",
    "relative_low_metric",
    "relative_low_threshold_or_boundary",
    "decision_known_time",
    "entry_execution_time",
    "opening_closing_auction_policy",
    "limit_and_suspension_policy",
    "ma12_interaction_rule",
    "style_conflict_policy",
    "independent_validation_or_source_basis",
    "t03_lineage_binding",
)

CONTRACT = {
    "version": "V5_T04_LOW_BUY_POSITION_SOURCE_READINESS_V1",
    "mode": "SOURCE_READINESS_ONLY",
    "source_fixed": {
        "low_buy_means_relative_intraday_low_position": True,
        "chase_means_relative_intraday_high_or_rising_position": True,
        "red_green_sign_alone_does_not_define_style": True,
        "eventual_full_day_low_is_forbidden_for_causal_entry": True,
        "ma12_context_is_distinct_from_intraday_low_buy_execution": True,
    },
    "parameter_search": False,
    "low_buy_position_preregistration_authorized": False,
    "trend_return_screen_authorized": False,
    "t02_t03_combination_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "intraday_reference_window": {
            "ready": False,
            "detail": "source says relative intraday low but does not define a backward-only reference window",
        },
        "intraday_data_source_and_frequency": {
            "ready": False,
            "detail": "source does not specify point-in-time bar source, interval or timestamp semantics",
        },
        "relative_low_metric": {
            "ready": False,
            "detail": "source does not define range position, percentile, VWAP distance or another mechanical low metric",
        },
        "relative_low_threshold_or_boundary": {
            "ready": False,
            "detail": "source gives no numeric cutoff for what counts as relatively low",
        },
        "decision_known_time": {
            "ready": False,
            "detail": "literal eventual full-day relative low is retrospective; a causal known-time proxy is unresolved",
        },
        "entry_execution_time": {
            "ready": False,
            "detail": "first executable timestamp after a causal low-position decision is unspecified",
        },
        "opening_closing_auction_policy": {
            "ready": False,
            "detail": "source does not state whether auction prints participate in the intraday reference",
        },
        "limit_and_suspension_policy": {
            "ready": False,
            "detail": "source does not define execution treatment for limit states, halts or missing bars",
        },
        "ma12_interaction_rule": {
            "ready": False,
            "detail": "T03 says low-buy around MA12, but the exact daily-context/intraday-entry conjunction remains undefined",
        },
        "style_conflict_policy": {
            "ready": False,
            "detail": "source distinguishes chase and low-buy mental models but does not define a machine conflict resolver",
        },
        "independent_validation_or_source_basis": {
            "ready": False,
            "detail": "no non-P&L basis yet fixes the causal intraday proxy choices",
        },
        "t03_lineage_binding": {
            "ready": True,
            "detail": "T04 binds the frozen T03 result so low-buy semantics cannot rewrite the source-fixed MA12/MA20/~20% literals",
        },
        "literal_relative_intraday_low": {
            "ready": True,
            "detail": "source explicitly defines low-buy by relative intraday low location",
        },
        "literal_color_independence": {
            "ready": True,
            "detail": "source explicitly explains that red/green sign alone does not determine chase versus low-buy",
        },
        "causality_guard": {
            "ready": True,
            "detail": "T04 forbids selecting the eventual full-day low because that would require future information",
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
        "status": "READY_FOR_LOW_BUY_POSITION_PREREGISTRATION" if ready else "DEFER_LOW_BUY_POSITION_PREREGISTRATION",
        "ready": ready,
        "missing_fields": missing,
        "not_ready": not_ready,
        "low_buy_position_preregistration_authorized": ready,
        "trend_return_screen_authorized": False,
        "t02_t03_combination_authorized": False,
        "effective_action": "WRITE_CAUSAL_INTRADAY_PREREGISTRATION" if ready else "SOURCE_AND_CAUSAL_INTRADAY_REPRESENTATION_ONLY",
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    for path in (SOURCE_REVIEW, T03_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)

    report = {
        "contract": CONTRACT,
        "lineage": {
            "source_review_sha256": sha256_file(SOURCE_REVIEW),
            "t03_result_sha256": sha256_file(T03_RESULT),
        },
        "evidence": evidence(),
    }
    report["decision"] = evaluate(report["evidence"])
    report["interpretation_boundary"] = (
        "T04 preserves the book's relative-intraday-low meaning of low-buy while refusing to use the eventual full-day low or fit a causal intraday proxy from returns."
    )
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
