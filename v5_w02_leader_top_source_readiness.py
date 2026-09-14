"""Fail-closed W02 readiness gate for W01 event identity.

W02 does not load market data or strategy returns.  It records which pieces of
the book-described bear-market leader pullback are directly specified and
which still require independent semantic evidence before any W01 event can be
preregistered.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_W02_LEADER_TOP_SOURCE_REVIEW.md"
M01_RESULT = ROOT / "V5_M01_RESULT.md"
M02_REVIEW = ROOT / "V5_M02_MARKET_CYCLE_SOURCE_REVIEW.md"
M02_RESULT = ROOT / "V5_M02_RESULT.md"
LEDGER = ROOT / "V5_BOOK_EVIDENCE_LEDGER.md"
OUT = ROOT / "output" / "v5_w02_leader_top_source_readiness"
REPORT = OUT / "report.json"

REQUIRED = (
    "bear_state_handoff",
    "leader_identity_basis",
    "prior_wave_qualification",
    "top_anchor_rule",
    "first_pullback_rule",
    "drawdown_basis",
    "drawdown_window",
    "drawdown_magnitude",
    "causal_decision_time",
    "event_reset_or_duplicate_rule",
    "independent_validation_or_source_basis",
    "upstream_lineage_binding",
)

CONTRACT = {
    "version": "V5_W02_LEADER_TOP_SOURCE_READINESS_V1",
    "mode": "SOURCE_READINESS_ONLY",
    "upstream_market_state": "V5_M02_MARKET_CYCLE_SOURCE_READINESS_V1",
    "source_fixed": {
        "drawdown_window_trading_sessions": [3, 7],
        "drawdown_magnitude_fraction_approx": [0.20, 0.25],
        "requires_bear_context": True,
        "requires_absolute_leader": True,
        "requires_first_post_top_event": True,
    },
    "required_for_w01_event_preregistration": list(REQUIRED),
    "parameter_search": False,
    "w01_event_preregistration_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "bear_state_handoff": {
            "ready": False,
            "detail": (
                "M02 is frozen DEFER_MARKET_CYCLE_CLASSIFIER_PREREGISTRATION; "
                "no validated causal bear-state handoff exists"
            ),
        },
        "leader_identity_basis": {
            "ready": False,
            "detail": (
                "source requires an absolute leader but does not define a unique point-in-time "
                "cross-sectional leader identity rule"
            ),
        },
        "prior_wave_qualification": {
            "ready": False,
            "detail": (
                "source context implies a preceding material advance/rebound but does not give a "
                "machine-ready wave qualification rule"
            ),
        },
        "top_anchor_rule": {
            "ready": False,
            "detail": (
                "source says the leader has topped but does not specify close/high anchor, adjustment basis, "
                "or causal confirmation timing"
            ),
        },
        "first_pullback_rule": {
            "ready": False,
            "detail": (
                "the source explicitly requires the first post-top opportunity, but a deterministic first-event "
                "rule cannot be fixed until the top anchor/reset semantics are independently defined"
            ),
        },
        "drawdown_basis": {
            "ready": False,
            "detail": (
                "20%-25% is source-fixed, but high-to-close/high-to-low/close-to-close and adjusted-price "
                "measurement semantics are unspecified"
            ),
        },
        "drawdown_window": {
            "ready": True,
            "detail": "primary source directly specifies approximately 3-7 trading sessions",
            "value": [3, 7],
            "unit": "trading_sessions",
        },
        "drawdown_magnitude": {
            "ready": True,
            "detail": "primary source directly specifies approximately 20%-25% decline",
            "value": [0.20, 0.25],
            "unit": "fraction",
            "approximate": True,
        },
        "causal_decision_time": {
            "ready": False,
            "detail": "source does not specify when all event conditions become known relative to close/open execution",
        },
        "event_reset_or_duplicate_rule": {
            "ready": False,
            "detail": (
                "source does not define how a later new high, failed first event, repeated setup or overlapping top "
                "resets event identity"
            ),
        },
        "independent_validation_or_source_basis": {
            "ready": False,
            "detail": (
                "no non-P&L basis yet resolves absolute-leader identity, top semantics, prior wave, first-event or "
                "drawdown measurement choices"
            ),
        },
        "upstream_lineage_binding": {
            "ready": True,
            "detail": "W02 can bind the frozen M01/M02 results, M02 review, source review and evidence ledger",
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
            "READY_FOR_W01_EVENT_PREREGISTRATION"
            if ready
            else "DEFER_W01_EVENT_PREREGISTRATION"
        ),
        "ready": ready,
        "missing_fields": missing_fields,
        "not_ready": not_ready,
        "w01_event_preregistration_authorized": ready,
        # Even source readiness can authorize only a later preregistration.
        # It never directly authorizes inspecting W01 returns or trading.
        "w01_return_screen_authorized": False,
        "effective_action": (
            "WRITE_SEPARATE_W01_EVENT_PREREGISTRATION"
            if ready
            else "SOURCE_AND_REPRESENTATION_RESEARCH_ONLY"
        ),
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def _lineage() -> dict[str, str]:
    paths = {
        "source_review_sha256": SOURCE_REVIEW,
        "m01_result_sha256": M01_RESULT,
        "m02_review_sha256": M02_REVIEW,
        "m02_result_sha256": M02_RESULT,
        "evidence_ledger_sha256": LEDGER,
    }
    return {name: sha256_file(path) for name, path in paths.items()}


def run() -> dict[str, Any]:
    for path in (SOURCE_REVIEW, M01_RESULT, M02_REVIEW, M02_RESULT, LEDGER):
        if not path.exists():
            raise FileNotFoundError(path)

    e = evidence()
    decision = evaluate(e)
    report = {
        "contract": CONTRACT,
        "lineage": _lineage(),
        "evidence": e,
        "decision": decision,
        "interpretation_boundary": (
            "The source directly fixes the approximate 3-7 session / 20%-25% event shape, but W02 does not "
            "manufacture the missing absolute-leader, top, first-event, drawdown-basis or bear-state semantics. "
            "A defer result keeps W01 returns closed."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
