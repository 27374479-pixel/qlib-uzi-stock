from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, Mapping

CONTRACT = {
    "version": "V5_W01_BEAR_PULLBACK_SOURCE_READINESS_V1",
    "mode": "SOURCE_READINESS_ONLY",
    "literal_source_parameters": {
        "pullback_window_sessions_min": 3,
        "pullback_window_sessions_max": 7,
        "drawdown_fraction_min": 0.20,
        "drawdown_fraction_max": 0.25,
        "first_post_top_occurrence": True,
    },
    "required_for_signal_preregistration": [
        "machine_ready_bear_market_state",
        "machine_ready_leader_identity",
        "prior_upward_wave_definition",
        "top_anchor_definition",
        "drawdown_measurement_basis",
        "market_stock_resonance_definition",
        "entry_timing_and_price",
        "exit_or_holding_rule",
        "economic_control_definition",
    ],
    "parameter_search": False,
    "return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}

DEFAULT_EVIDENCE: Dict[str, Dict[str, object]] = {
    "three_to_seven_session_window": {
        "ready": True,
        "detail": "primary source explicitly gives a 3-7 trading-session pullback window",
    },
    "twenty_to_twentyfive_percent_drawdown": {
        "ready": True,
        "detail": "primary source explicitly gives roughly a 20%-25% decline",
    },
    "first_post_top_occurrence": {
        "ready": True,
        "detail": "primary source explicitly frames the setup as the first left-side opportunity after the top",
    },
    "bear_market_context_required": {
        "ready": True,
        "detail": "primary source conditions the setup on bear-market context; another trader separately links low-buy usefulness to bear markets",
    },
    "leader_context_required": {
        "ready": True,
        "detail": "primary source explicitly requires the stock to be a leader",
    },
    "machine_ready_bear_market_state": {
        "ready": False,
        "detail": "reviewed source does not provide a point-in-time numeric or deterministic bear-market classifier",
    },
    "machine_ready_leader_identity": {
        "ready": False,
        "detail": "reviewed source does not specify market-total leader, sector leader, board-height leader, return-rank leader, or another deterministic identity rule",
    },
    "prior_upward_wave_definition": {
        "ready": False,
        "detail": "the prerequisite prior large upward wave/rebound has no numeric return, duration, or structure definition",
    },
    "top_anchor_definition": {
        "ready": False,
        "detail": "the source does not define the top anchor point mechanically",
    },
    "drawdown_measurement_basis": {
        "ready": False,
        "detail": "the source does not specify high-to-close versus high-to-low, price adjustment basis, or exact boundary convention",
    },
    "market_stock_resonance_definition": {
        "ready": False,
        "detail": "the market/stock resonance or inflection-area language is not mapped to a deterministic observable",
    },
    "entry_timing_and_price": {
        "ready": False,
        "detail": "entering after a 20%-25% pullback is not given an executable timestamp or price rule",
    },
    "exit_or_holding_rule": {
        "ready": False,
        "detail": "the exact setup does not include a deterministic exit or holding horizon",
    },
    "economic_control_definition": {
        "ready": False,
        "detail": "the source does not define a matched economic control for a falsifiable relative test",
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def evaluate_readiness(evidence: Mapping[str, Mapping[str, object]]) -> dict:
    missing_fields = []
    not_ready = []
    for field in CONTRACT["required_for_signal_preregistration"]:
        item = evidence.get(field)
        if item is None:
            missing_fields.append(field)
            continue
        if not bool(item.get("ready")):
            not_ready.append({
                "field": field,
                "detail": str(item.get("detail", "not ready")),
            })

    ready = not missing_fields and not not_ready
    return {
        "status": "READY_FOR_SIGNAL_PREREGISTRATION_ONLY" if ready else "DEFER_BEAR_PULLBACK_PREREGISTRATION",
        "ready": ready,
        "missing_fields": missing_fields,
        "not_ready": not_ready,
        "signal_preregistration_authorized": ready,
        # Even a source-ready result authorizes only writing a separate preregistration.
        "return_screen_authorized": False,
        "effective_action": "WRITE_SEPARATE_PREREGISTRATION" if ready else "SOURCE_EXTRACTION_ONLY",
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def build_report(source_review: Path, evidence: Mapping[str, Mapping[str, object]] | None = None) -> dict:
    ev = dict(DEFAULT_EVIDENCE if evidence is None else evidence)
    return {
        "contract": CONTRACT,
        "source_review_sha256": sha256_file(source_review),
        "evidence": ev,
        "decision": evaluate_readiness(ev),
        "interpretation_boundary": (
            "W01 preserves the literal 3-7 session / 20%-25% / first-post-top structure, "
            "but does not manufacture bear-market, leader, top, entry or exit definitions from historical returns. "
            "A defer result forbids a P&L screen."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-review", default="V5_W01_BEAR_PULLBACK_SOURCE_REVIEW.md")
    parser.add_argument("--output", default="output/v5_w01_bear_pullback_source_readiness/report.json")
    args = parser.parse_args()

    source_review = Path(args.source_review)
    if not source_review.is_file():
        raise FileNotFoundError(source_review)

    report = build_report(source_review)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
