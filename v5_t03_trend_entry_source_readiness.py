"""Fail-closed T03 readiness gate for source-grounded trend-stock entries."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_T03_TREND_ENTRY_SOURCE_REVIEW.md"
T02_RESULT = ROOT / "V5_T02_RESULT.md"
OUT = ROOT / "output" / "v5_t03_trend_entry_source_readiness"
REPORT = OUT / "report.json"

REQUIRED = (
    "trend_stock_predicate",
    "price_adjustment_basis",
    "ma_calculation_basis",
    "ma12_low_buy_observation_rule",
    "ma12_proximity_or_cross_semantics",
    "ma12_known_time_and_entry_time",
    "ma20_break_observation_rule",
    "ma20_caution_action_semantics",
    "acute_selloff_anchor",
    "acute_selloff_measurement_formula",
    "acute_selloff_window",
    "acute_selloff_known_time_and_entry_time",
    "condition_interaction_precedence",
    "position_and_exit_semantics",
    "independent_validation_or_source_basis",
    "t02_lineage_binding",
)

CONTRACT = {
    "version": "V5_T03_TREND_ENTRY_SOURCE_READINESS_V1",
    "mode": "SOURCE_READINESS_ONLY",
    "source_fixed": {
        "low_buy_ma_period_sessions": 12,
        "caution_ma_period_sessions": 20,
        "acute_selloff_fraction_approx": 0.20,
    },
    "parameter_search": False,
    "trend_entry_preregistration_authorized": False,
    "trend_return_screen_authorized": False,
    "t02_combination_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def evidence() -> dict[str, dict[str, Any]]:
    unresolved = {
        "trend_stock_predicate": "source conditions the rules on trend stocks but does not machine-define that prerequisite state",
        "price_adjustment_basis": "source does not specify raw/adjusted price or corporate-action treatment",
        "ma_calculation_basis": "source gives periods but not exact adjusted-price/min-period/missing-session calculation semantics",
        "ma12_low_buy_observation_rule": "source does not choose touch/low-below/close-near/reclaim or another MA12 low-buy observation",
        "ma12_proximity_or_cross_semantics": "source does not provide a numerical proximity/cross tolerance around MA12",
        "ma12_known_time_and_entry_time": "earliest causal knowledge and executable entry time for the MA12 condition are unspecified",
        "ma20_break_observation_rule": "source does not specify intraday low versus close versus persistence for breaking MA20",
        "ma20_caution_action_semantics": "the word caution does not machine-define no-entry/reduce/exit/tighten-risk behavior",
        "acute_selloff_anchor": "source does not define the starting high/close/swing anchor for the approximate 20% selloff",
        "acute_selloff_measurement_formula": "source does not define high-to-low/close-to-close or other drawdown formula",
        "acute_selloff_window": "the adjective acute does not supply a fixed elapsed-session window",
        "acute_selloff_known_time_and_entry_time": "causal observation and first executable entry time after the selloff are unspecified",
        "condition_interaction_precedence": "source does not resolve conflicts among MA12 low-buy, MA20 caution and ~20% acute-selloff conditions",
        "position_and_exit_semantics": "source passage does not define sizing, stop, holding horizon, exit or re-entry for this entry set",
        "independent_validation_or_source_basis": "no non-P&L basis yet resolves the prerequisite state and execution choices",
    }
    out: dict[str, dict[str, Any]] = {
        field: {"ready": False, "detail": detail} for field, detail in unresolved.items()
    }
    out["t02_lineage_binding"] = {
        "ready": True,
        "detail": "T03 binds the frozen T02 result so entry literals cannot silently rewrite T02 exit semantics",
    }
    out["literal_ma12"] = {
        "ready": True,
        "detail": "source explicitly names a 12-session moving-average line for trend-stock low-buy",
    }
    out["literal_ma20"] = {
        "ready": True,
        "detail": "source explicitly says breaking the 20-session line warrants caution",
    }
    out["literal_acute_selloff_20pct"] = {
        "ready": True,
        "detail": "source explicitly identifies an acute selloff around 20% as a possible good buy area",
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
        "status": "READY_FOR_TREND_ENTRY_PREREGISTRATION" if ready else "DEFER_TREND_ENTRY_PREREGISTRATION",
        "ready": ready,
        "missing_fields": missing,
        "not_ready": not_ready,
        "trend_entry_preregistration_authorized": ready,
        "trend_return_screen_authorized": False,
        "t02_combination_authorized": False,
        "effective_action": (
            "WRITE_SEPARATE_TREND_ENTRY_PREREGISTRATION"
            if ready
            else "SOURCE_AND_TREND_STATE_REPRESENTATION_ONLY"
        ),
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    for path in (SOURCE_REVIEW, T02_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)
    report = {
        "contract": CONTRACT,
        "lineage": {
            "source_review_sha256": sha256_file(SOURCE_REVIEW),
            "t02_result_sha256": sha256_file(T02_RESULT),
        },
        "evidence": evidence(),
    }
    report["decision"] = evaluate(report["evidence"])
    report["interpretation_boundary"] = (
        "T03 preserves the source-fixed 12-session MA, 20-session MA and approximately 20% acute-selloff literals, "
        "but does not infer trend-state, touch/break, drawdown, interaction or execution semantics from P&L."
    )
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
