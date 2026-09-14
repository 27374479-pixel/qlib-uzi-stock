"""Fail-closed W06 readiness gate for W01 first-event/reset semantics."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_W06_FIRST_EVENT_RESET_SOURCE_REVIEW.md"
W05_RESULT = ROOT / "V5_W05_RESULT.md"
W04_RESULT = ROOT / "V5_W04_RESULT.md"
W03_RESULT = ROOT / "V5_W03_RESULT.md"
W02_RESULT = ROOT / "V5_W02_RESULT.md"
M02_RESULT = ROOT / "V5_M02_RESULT.md"
OUT = ROOT / "output" / "v5_w06_first_event_reset_source_readiness"
REPORT = OUT / "report.json"

REQUIRED = (
    "episode_start_rule",
    "candidate_observation_field",
    "first_event_predicate",
    "approx_drawdown_semantics",
    "window_boundary_semantics",
    "pre_window_observation_policy",
    "event_consumption_rule",
    "failed_or_unfilled_event_policy",
    "pre_entry_new_high_reset_rule",
    "replacement_top_rule",
    "same_session_ordering_rule",
    "missing_or_suspended_session_rule",
    "event_known_time_and_entry_time",
    "independent_validation_or_source_basis",
    "upstream_lineage_binding",
)

CONTRACT = {
    "version": "V5_W06_FIRST_EVENT_RESET_SOURCE_READINESS_V1",
    "mode": "SOURCE_READINESS_ONLY",
    "source_fixed": {
        "ordinal_requirement": "first_post_top_left_side_opportunity",
        "drawdown_window_trading_sessions_approx": [3, 7],
        "drawdown_fraction_approx": [0.20, 0.25],
        "later_candidates_may_not_replace_first_based_on_pnl": True,
        "post_entry_new_high_description_is_not_pre_entry_reset_rule": True,
    },
    "parameter_search": False,
    "first_event_reset_preregistration_authorized": False,
    "w01_event_preregistration_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def evidence() -> dict[str, dict[str, Any]]:
    unresolved = {
        "episode_start_rule": "top confirmation/known-time remains unresolved, so the episode start is not machine-ready",
        "candidate_observation_field": "source does not choose close, low or another completed field for candidate eligibility",
        "first_event_predicate": "source says first left-side opportunity but does not state the deterministic qualifying predicate",
        "approx_drawdown_semantics": "approximately 20%-25% is source-fixed but band/minimum/target interpretation is unspecified",
        "window_boundary_semantics": "approximately 3-7 sessions is source-fixed but session-zero and exact inclusive boundaries are unspecified",
        "pre_window_observation_policy": "source does not say whether pre-day-3 observations can consume/disqualify the first event",
        "event_consumption_rule": "source does not say whether observation, executability, order or fill consumes the event",
        "failed_or_unfilled_event_policy": "source does not say whether execution failure permits a later candidate",
        "pre_entry_new_high_reset_rule": "source does not state whether a new high before entry resets/invalidate the old post-top episode",
        "replacement_top_rule": "source does not define whether/how a later higher high becomes a replacement top anchor",
        "same_session_ordering_rule": "source does not define ordering among multiple same-session candidate observations",
        "missing_or_suspended_session_rule": "source does not specify market-session versus stock-session handling around suspensions/missing bars",
        "event_known_time_and_entry_time": "source does not state the earliest causal event-known time or executable entry timestamp",
        "independent_validation_or_source_basis": "no non-P&L basis currently resolves the state-machine choices",
    }
    out: dict[str, dict[str, Any]] = {
        field: {"ready": False, "detail": detail} for field, detail in unresolved.items()
    }
    out["upstream_lineage_binding"] = {
        "ready": True,
        "detail": "W06 binds frozen M02 and W02-W05 results plus its own source review",
    }
    out["literal_firstness"] = {
        "ready": True,
        "detail": "primary source explicitly privileges the first post-top left-side opportunity",
    }
    out["literal_window_and_drawdown_shape"] = {
        "ready": True,
        "detail": "primary source gives approximate 3-7 trading-session and 20%-25% decline shape",
    }
    out["post_entry_new_high_is_distinct"] = {
        "ready": True,
        "detail": "W05 preserves post-entry new-high description without treating it as a pre-entry reset rule",
    }
    return out


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
            "READY_FOR_FIRST_EVENT_RESET_PREREGISTRATION"
            if ready
            else "DEFER_FIRST_EVENT_RESET_PREREGISTRATION"
        ),
        "ready": ready,
        "missing_fields": missing,
        "not_ready": not_ready,
        "first_event_reset_preregistration_authorized": ready,
        "w01_event_preregistration_authorized": False,
        "w01_return_screen_authorized": False,
        "effective_action": (
            "WRITE_SEPARATE_FIRST_EVENT_RESET_PREREGISTRATION"
            if ready
            else "SOURCE_AND_STATE_MACHINE_RESEARCH_ONLY"
        ),
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    for path in (SOURCE_REVIEW, W05_RESULT, W04_RESULT, W03_RESULT, W02_RESULT, M02_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)

    report = {
        "contract": CONTRACT,
        "lineage": {
            "source_review_sha256": sha256_file(SOURCE_REVIEW),
            "w05_result_sha256": sha256_file(W05_RESULT),
            "w04_result_sha256": sha256_file(W04_RESULT),
            "w03_result_sha256": sha256_file(W03_RESULT),
            "w02_result_sha256": sha256_file(W02_RESULT),
            "m02_result_sha256": sha256_file(M02_RESULT),
        },
        "evidence": evidence(),
    }
    report["decision"] = evaluate(report["evidence"])
    report["interpretation_boundary"] = (
        "W06 preserves the source's ordinal first-opportunity constraint but refuses to invent the episode, "
        "eligibility, consumption or reset state machine from strategy returns."
    )
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
