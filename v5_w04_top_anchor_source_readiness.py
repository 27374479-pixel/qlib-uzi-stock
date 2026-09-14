"""Fail-closed W04 source-readiness gate for W01 top/drawdown semantics."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_W04_TOP_ANCHOR_SOURCE_REVIEW.md"
W03_RESULT = ROOT / "V5_W03_RESULT.md"
W02_RESULT = ROOT / "V5_W02_RESULT.md"
M02_RESULT = ROOT / "V5_M02_RESULT.md"
LEDGER = ROOT / "V5_BOOK_EVIDENCE_LEDGER.md"
OUT = ROOT / "output" / "v5_w04_top_anchor_source_readiness"
REPORT = OUT / "report.json"

REQUIRED = (
    "top_price_field",
    "price_adjustment_basis",
    "preceding_wave_anchor_scope",
    "top_confirmation_rule",
    "top_known_time",
    "session_zero_and_elapsed_counting",
    "drawdown_observation_field",
    "drawdown_formula",
    "drawdown_threshold_interpretation",
    "first_qualifying_event_rule",
    "new_high_reset_rule",
    "missing_or_suspended_session_rule",
    "decision_and_entry_time",
    "independent_validation_or_source_basis",
    "upstream_lineage_binding",
)

CONTRACT = {
    "version": "V5_W04_TOP_ANCHOR_SOURCE_READINESS_V1",
    "mode": "SOURCE_READINESS_ONLY",
    "source_fixed": {
        "event_order": ["leader_top", "decline", "first_left_side_opportunity"],
        "elapsed_trading_sessions_approx": [3, 7],
        "decline_fraction_approx": [0.20, 0.25],
    },
    "non_transfer_rule": "trend-stock three-day-no-new-high exit rule is not a W01 top definition",
    "parameter_search": False,
    "top_anchor_preregistration_authorized": False,
    "w01_event_preregistration_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "top_price_field": {
            "ready": False,
            "detail": "source says the leader topped but does not choose intraday high, close or another exact price field",
        },
        "price_adjustment_basis": {
            "ready": False,
            "detail": "source does not specify raw/adjusted price treatment or corporate-action semantics",
        },
        "preceding_wave_anchor_scope": {
            "ready": False,
            "detail": "source context requires a prior advance but does not define the backward-only wave/anchor scope",
        },
        "top_confirmation_rule": {
            "ready": False,
            "detail": "source does not state how a top is confirmed without future-looking local-maximum labelling",
        },
        "top_known_time": {
            "ready": False,
            "detail": "earliest causal timestamp at which the top may be treated as known is unspecified",
        },
        "session_zero_and_elapsed_counting": {
            "ready": False,
            "detail": "3-7 trading sessions are source-fixed approximately but top-day/day-1 counting semantics are not stated",
        },
        "drawdown_observation_field": {
            "ready": False,
            "detail": "source does not choose current close, low or another field for measuring the post-top decline",
        },
        "drawdown_formula": {
            "ready": False,
            "detail": "source gives 20%-25% magnitude but not high-to-close/high-to-low/close-to-close numerator/denominator semantics",
        },
        "drawdown_threshold_interpretation": {
            "ready": False,
            "detail": "approximately 20%-25% is literal source evidence but exact inclusive/exclusive mechanical treatment is not specified",
        },
        "first_qualifying_event_rule": {
            "ready": False,
            "detail": "first post-top event cannot be deterministic until top, counting and drawdown semantics are fixed",
        },
        "new_high_reset_rule": {
            "ready": False,
            "detail": "source does not state whether and how a later new high resets the candidate top/event clock",
        },
        "missing_or_suspended_session_rule": {
            "ready": False,
            "detail": "source does not state how stock suspensions/missing bars interact with the market trading-session window",
        },
        "decision_and_entry_time": {
            "ready": False,
            "detail": "source does not specify the first executable timestamp after the qualifying observation",
        },
        "independent_validation_or_source_basis": {
            "ready": False,
            "detail": "no non-P&L basis yet resolves top anchor, confirmation, measurement or execution choices",
        },
        "upstream_lineage_binding": {
            "ready": True,
            "detail": "W04 can bind frozen W02/W03/M02 results, source review and evidence ledger",
        },
        "trend_three_day_exit_transfer": {
            "ready": False,
            "detail": "separate trend-stock three-day-no-new-high exit rule is explicitly not transferred into W01 top semantics",
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
        "status": "READY_FOR_TOP_ANCHOR_PREREGISTRATION" if ready else "DEFER_TOP_ANCHOR_PREREGISTRATION",
        "ready": ready,
        "missing_fields": missing,
        "not_ready": not_ready,
        "top_anchor_preregistration_authorized": ready,
        "w01_event_preregistration_authorized": False,
        "w01_return_screen_authorized": False,
        "effective_action": "WRITE_SEPARATE_TOP_ANCHOR_PREREGISTRATION" if ready else "SOURCE_AND_REPRESENTATION_RESEARCH_ONLY",
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    for path in (SOURCE_REVIEW, W03_RESULT, W02_RESULT, M02_RESULT, LEDGER):
        if not path.exists():
            raise FileNotFoundError(path)
    report = {
        "contract": CONTRACT,
        "lineage": {
            "source_review_sha256": sha256_file(SOURCE_REVIEW),
            "w03_result_sha256": sha256_file(W03_RESULT),
            "w02_result_sha256": sha256_file(W02_RESULT),
            "m02_result_sha256": sha256_file(M02_RESULT),
            "evidence_ledger_sha256": sha256_file(LEDGER),
        },
        "evidence": evidence(),
    }
    report["decision"] = evaluate(report["evidence"])
    report["interpretation_boundary"] = (
        "W04 preserves the source-fixed approximate 3-7-session / 20%-25% shape but refuses to choose top price, "
        "confirmation lag, drawdown field/formula or execution timing from strategy returns or unrelated trend rules."
    )
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
