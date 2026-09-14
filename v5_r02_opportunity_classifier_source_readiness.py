"""Source-readiness gate for a future numeric opportunity classifier.

R02 deliberately runs before any market-state return/P&L screen.  It asks
whether the supplied-book evidence is machine-defensible enough to preregister
a numeric OPPORTUNITY_PRESENT / NO_TRADE classifier without inventing market
thresholds from historical outcomes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_R02_OPPORTUNITY_CLASSIFIER_SOURCE_REVIEW.md"
OUT = ROOT / "output" / "v5_r02_opportunity_classifier_source_readiness"
REPORT = OUT / "report.json"

REQUIRED_FOR_CLASSIFIER_PREREGISTRATION = (
    "point_in_time_market_opportunity_observable",
    "deterministic_state_mapping",
    "numeric_threshold_basis_if_required",
    "ambiguous_evidence_unknown_policy",
    "noncircular_validation_target",
)

DEFAULT_EVIDENCE: dict[str, dict[str, Any]] = {
    "cash_no_trade_architecture": {
        "ready": True,
        "detail": "book explicitly treats cash/waiting as legitimate when timing is immature or market conditions are unfavorable",
    },
    "market_quality_conditions_method_choice": {
        "ready": True,
        "detail": "book distinguishes stronger and poorer market conditions and changes the preferred method accordingly",
    },
    "market_cyclicality": {
        "ready": True,
        "detail": "book explicitly describes market cycles and phase changes",
    },
    "large_decline_not_sufficient_buy_reason": {
        "ready": True,
        "detail": "bear-market passage explicitly rejects prior decline alone as a sufficient reason to buy",
    },
    "isolated_ma20_stock_veto": {
        "ready": True,
        "detail": "20-day-average downward direction is directly observable but is an individual-stock veto, not a market classifier; K01 did not validate the isolated veto economically",
    },
    "point_in_time_market_opportunity_observable": {
        "ready": False,
        "detail": "good/poor market, settled decline and recovery are named but not machine-defined in the reviewed passages",
    },
    "deterministic_state_mapping": {
        "ready": False,
        "detail": "source does not map observable market data deterministically to UNKNOWN/NO_TRADE/OPPORTUNITY_PRESENT",
    },
    "numeric_threshold_basis_if_required": {
        "ready": False,
        "detail": "source gives no defensible breadth/index/limit-up/turnover/sentiment threshold for the opportunity state",
    },
    "ambiguous_evidence_unknown_policy": {
        "ready": True,
        "detail": "R01 already freezes fail-closed UNKNOWN -> CASH_ONLY behavior; ambiguity does not activate opportunity",
    },
    "noncircular_validation_target": {
        "ready": False,
        "detail": "reviewed passages do not define an independent machine label for opportunity; strategy P&L must not be used to define the state it is meant to predict",
    },
}

CONTRACT = {
    "version": "V5_R02_OPPORTUNITY_CLASSIFIER_SOURCE_READINESS_V1",
    "required_for_classifier_preregistration": list(REQUIRED_FOR_CLASSIFIER_PREREGISTRATION),
    "parameter_search": False,
    "numeric_classifier_implemented": False,
    "classifier_return_screen_authorized": False,
    "x02_gate_change_authorized": False,
    "portfolio_optimization_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "fallback": "UNKNOWN -> CASH_ONLY",
}


def evaluate(evidence: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    missing = [name for name in REQUIRED_FOR_CLASSIFIER_PREREGISTRATION if name not in evidence]
    not_ready: list[dict[str, str]] = []
    for name in REQUIRED_FOR_CLASSIFIER_PREREGISTRATION:
        item = evidence.get(name, {})
        if item.get("ready") is not True:
            not_ready.append({"field": name, "detail": str(item.get("detail", "not ready"))})
    ready = not missing and not not_ready
    return {
        "status": (
            "READY_FOR_NUMERIC_CLASSIFIER_PREREGISTRATION"
            if ready
            else "DEFER_NUMERIC_CLASSIFIER_PREREGISTRATION"
        ),
        "ready": ready,
        "missing_fields": missing,
        "not_ready": not_ready,
        "classifier_preregistration_authorized": ready,
        "classifier_return_screen_authorized": False,
        "numeric_classifier_implemented": False,
        "effective_opportunity_state": "UNKNOWN",
        "action": "CASH_ONLY",
        "x02_gate_change_authorized": False,
        "portfolio_optimization_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    if not SOURCE_REVIEW.exists():
        raise FileNotFoundError(SOURCE_REVIEW)
    decision = evaluate(DEFAULT_EVIDENCE)
    payload = {
        "contract": CONTRACT,
        "source_review_sha256": sha256_file(SOURCE_REVIEW),
        "evidence": DEFAULT_EVIDENCE,
        "decision": decision,
        "interpretation_boundary": (
            "R02 evaluates source readiness before any classifier P&L. A DEFER result cannot be bypassed by "
            "searching numeric market thresholds against X02 or other strategy returns."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


if __name__ == "__main__":
    run()
