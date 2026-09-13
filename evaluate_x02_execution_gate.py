"""Pre-registered interpretation gate for the frozen X02 execution audit.

This gate does not choose parameters or optimize a strategy. It answers only
whether the exact frozen X02 spec survives the conservative next-record
execution check well enough to justify forward paper trading. It never
authorizes live trading.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "x02_reproduction_20260912"
BAR_AUDIT = OUT / "minute_bar_structure_audit.json"
COMPARISON = OUT / "next_bar_execution_comparison.json"
OUTPUT_JSON = OUT / "execution_gate.json"
OUTPUT_MD = OUT / "execution_gate.md"
PRIMARY_SPEC = "original_gate_CONSERVATIVE"
PRIMARY_PERIOD = "later"
REQUIRED_BAR_INFERENCE = "CONSISTENT_WITH_END_LABELLED_5M_NOT_PROOF"


def evaluate(bar_audit: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    aggregate = bar_audit.get("aggregate", {})
    bar_valid = bool(bar_audit.get("validation", {}).get("pass"))
    bar_inference = aggregate.get("inference")
    lineage_valid = bool(comparison.get("lineage", {}).get("pass"))
    if not bar_valid:
        reasons.append("minute-bar structure audit did not pass")
    if bar_inference != REQUIRED_BAR_INFERENCE:
        reasons.append("minute-bar label structure remains ambiguous for the next-record interpretation")
    if not lineage_valid:
        reasons.append("comparison lineage validation did not pass")

    row = comparison.get("results", {}).get(PRIMARY_SPEC, {}).get(PRIMARY_PERIOD)
    if row is None:
        reasons.append(f"missing primary result {PRIMARY_SPEC}/{PRIMARY_PERIOD}")
        primary_cagr = None
    else:
        primary_cagr = row.get("next_bar", {}).get("cagr")
        if primary_cagr is None:
            reasons.append("primary next-bar CAGR is missing")

    if reasons:
        status = "TECHNICALLY_INVALID"
        paper_trading_authorized = False
    elif float(primary_cagr) <= 0:
        status = "EXECUTION_NOT_ROBUST"
        paper_trading_authorized = False
        reasons.append("primary historical-later CONSERVATIVE next-record CAGR is not positive")
    else:
        status = "PROVISIONALLY_ROBUST_FOR_PAPER_TRADING_ONLY"
        paper_trading_authorized = True
        reasons.append("primary historical-later CONSERVATIVE next-record CAGR remains positive")

    primary = row or {}
    execution = primary.get("execution", {})
    retention = primary.get("positive_metric_retention", {})
    return {
        "gate": "X02_EXECUTION_SURVIVAL_GATE_V2",
        "pre_registered_rule": (
            "Technical validity and bar-label structural evidence are mandatory. For the exact frozen spec, the minimal historical "
            "execution-survival condition is positive next-record CAGR for original_gate_CONSERVATIVE in the 2024+ historical-later segment."
        ),
        "status": status,
        "paper_trading_authorized": paper_trading_authorized,
        "live_trading_authorized": False,
        "parameter_search_authorized": False,
        "post_result_retuning_authorized": False,
        "primary_spec": PRIMARY_SPEC,
        "primary_period": PRIMARY_PERIOD,
        "primary_next_bar_cagr": primary_cagr,
        "primary_cagr_retention": retention.get("cagr"),
        "primary_fill_rate": execution.get("fill_rate"),
        "primary_cash_slots": execution.get("cash_slots"),
        "primary_mean_entry_slippage_vs_1445": execution.get("mean_entry_slippage_vs_1445"),
        "primary_p90_entry_slippage_vs_1445": execution.get("p90_entry_slippage_vs_1445"),
        "primary_unfilled_reasons": execution.get("unfilled_reasons"),
        "primary_next_bar_max_drawdown": primary.get("next_bar", {}).get("max_drawdown"),
        "bar_label_inference": bar_inference,
        "required_bar_label_inference": REQUIRED_BAR_INFERENCE,
        "reasons": reasons,
        "interpretation_boundary": (
            "A positive historical-later result is only a minimum execution-survival check. The period is not pristine OOS, "
            "and this gate is not evidence of future profitability. A positive gate permits forward paper trading only."
        ),
    }


def render_markdown(result: dict[str, Any]) -> str:
    def pct(value: object) -> str:
        try:
            return f"{float(value):.2%}"
        except (TypeError, ValueError):
            return "n/a"

    lines = [
        "# X02 execution survival gate",
        "",
        f"**Status:** `{result['status']}`",
        "",
        f"- Primary: `{result['primary_spec']}` / `{result['primary_period']}`",
        f"- Next-record CAGR: {pct(result.get('primary_next_bar_cagr'))}",
        f"- CAGR retention vs legacy: {pct(result.get('primary_cagr_retention'))}",
        f"- Fill rate: {pct(result.get('primary_fill_rate'))}",
        f"- Mean filled entry slippage vs 14:45: {pct(result.get('primary_mean_entry_slippage_vs_1445'))}",
        f"- P90 filled entry slippage vs 14:45: {pct(result.get('primary_p90_entry_slippage_vs_1445'))}",
        f"- Next-record max drawdown: {pct(result.get('primary_next_bar_max_drawdown'))}",
        f"- Bar-label inference: `{result.get('bar_label_inference')}`",
        f"- Paper trading authorized by this research gate: {result['paper_trading_authorized']}",
        f"- Live trading authorized: {result['live_trading_authorized']}",
        "",
        "This is a historical execution-survival gate, not a prediction of future returns. No post-result parameter retuning is authorized.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    if not BAR_AUDIT.exists() or not COMPARISON.exists():
        raise SystemExit("run the X02 execution-validation chain through comparison first")
    bar_audit = json.loads(BAR_AUDIT.read_text(encoding="utf-8"))
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    result = evaluate(bar_audit, comparison)
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(render_markdown(result), encoding="utf-8")
    print(render_markdown(result))
    if result["status"] == "TECHNICALLY_INVALID":
        raise SystemExit("execution gate is technically invalid; fix audit failures before interpretation")


if __name__ == "__main__":
    main()
