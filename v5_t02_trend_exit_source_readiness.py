"""Fail-closed source-readiness gate for book-derived trend-stock exit rules.

T02 intentionally performs no return screen. It preserves the literal numeric
source facts (3 sessions, 10-day line) while refusing to invent the prerequisite
trend-state definition or execution semantics from historical P&L.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_T02_TREND_EXIT_SOURCE_REVIEW.md"
OUTPUT = ROOT / "output" / "v5_t02_trend_exit_source_readiness" / "report.json"

CONTRACT: dict[str, Any] = {
    "version": "V5_T02_TREND_EXIT_SOURCE_READINESS_V1",
    "mode": "SOURCE_READINESS_ONLY",
    "literal_source_parameters": {
        "no_new_high_window_sessions": 3,
        "moving_average_period_sessions": 10,
    },
    "required_for_exit_preregistration": [
        "machine_ready_trend_state",
        "three_day_anchor_definition",
        "three_day_exit_execution_timing",
        "ma10_break_price_definition",
        "ma10_exit_execution_timing",
        "price_adjustment_basis",
        "exit_interaction_policy",
        "reentry_policy",
    ],
    "parameter_search": False,
    "return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}

EVIDENCE: dict[str, dict[str, Any]] = {
    "three_day_window": {
        "ready": True,
        "detail": "source explicitly gives three days for the no-intraday-new-high exit concept",
    },
    "ma10_period": {
        "ready": True,
        "detail": "source explicitly names the 10-day line as a short-wave profit-taking floor",
    },
    "trend_context_required": {
        "ready": True,
        "detail": "source conditions these rules on trend-stock/trend-bull context rather than the entire universe",
    },
    "machine_ready_trend_state": {
        "ready": False,
        "detail": "reviewed passages do not deterministically define trend stock, trend bull, main rise, or staged advance",
    },
    "three_day_anchor_definition": {
        "ready": False,
        "detail": "source does not specify whether the three-session count begins after entry, a local high, or another event",
    },
    "three_day_exit_execution_timing": {
        "ready": False,
        "detail": "source does not define the executable timing/price after the third no-new-high session",
    },
    "ma10_break_price_definition": {
        "ready": False,
        "detail": "source does not specify intraday low versus close or another precise definition of breaking the 10-day line",
    },
    "ma10_exit_execution_timing": {
        "ready": False,
        "detail": "source does not define the executable timing/price after an MA10 break",
    },
    "price_adjustment_basis": {
        "ready": False,
        "detail": "source does not specify adjusted versus nominal price series for the moving-average test",
    },
    "exit_interaction_policy": {
        "ready": False,
        "detail": "source does not define precedence when the three-day and MA10 exits occur together or near each other",
    },
    "reentry_policy": {
        "ready": False,
        "detail": "source does not define whether or when a position may be re-entered after an exit",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_report() -> dict[str, Any]:
    if not SOURCE_REVIEW.exists():
        raise FileNotFoundError(SOURCE_REVIEW)

    missing = [key for key in CONTRACT["required_for_exit_preregistration"] if key not in EVIDENCE]
    not_ready = [
        {"field": key, "detail": EVIDENCE[key]["detail"]}
        for key in CONTRACT["required_for_exit_preregistration"]
        if key in EVIDENCE and EVIDENCE[key]["ready"] is not True
    ]
    ready = not missing and not not_ready

    decision = {
        "status": "READY_FOR_TREND_EXIT_PREREGISTRATION" if ready else "DEFER_TREND_EXIT_PREREGISTRATION",
        "ready": ready,
        "missing_fields": missing,
        "not_ready": not_ready,
        "exit_preregistration_authorized": ready,
        "return_screen_authorized": False,
        "effective_action": "SOURCE_EXTRACTION_ONLY" if not ready else "PREREGISTRATION_ONLY",
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }

    return {
        "contract": CONTRACT,
        "source_review_sha256": sha256_file(SOURCE_REVIEW),
        "evidence": EVIDENCE,
        "decision": decision,
        "interpretation_boundary": (
            "T02 preserves literal 3-session/10-day parameters but does not manufacture a trend-state definition "
            "or execution convention from historical returns. A DEFER result forbids a P&L screen."
        ),
    }


def main() -> None:
    report = build_report()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
