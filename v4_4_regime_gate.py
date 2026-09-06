"""V4.4 causal market-regime gating for the V4.3 long-only strategy.

Purpose:
V4.3 found a sharp regime split: recent 2024-2026 signal-only Top-N variants
were profitable, while 2021-2023 were strongly negative. This script tests
whether *causal market state known at T-1 close* can explain/filter that split.

No date/year gate is allowed. No same-day intraday confirmation is used.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_4_regime_gate.json"

LIMIT_BUFFER = 0.005
TOP_NS = (3, 5, 10)
EXITS = ("09:35", "09:40", "10:00")
COSTS = ("BASE", "CONSERVATIVE")


def _gate_mask(x: pd.DataFrame, gate: str) -> pd.Series:
    weak = x["signal_weak_market"].fillna(True).astype(bool)
    breadth = x["breadth"].fillna(-1.0)
    breadth5 = x["breadth5"].fillna(-1.0)
    money = x["money_effect"].fillna(-1.0)

    if gate == "NOT_WEAK":
        return ~weak
    if gate == "BREADTH_POS":
        return breadth > 0
    if gate == "BREADTH5_POS":
        return breadth5 > 0
    if gate == "MONEY_POS":
        return money > 0
    if gate == "BREADTH_AND_MONEY":
        return (breadth > 0) & (money > 0)
    if gate == "BREADTH5_AND_MONEY":
        return (breadth5 > 0) & (money > 0)
    if gate == "STRONG_ALL":
        return (~weak) & (breadth5 > 0) & (money > 0)
    raise ValueError(gate)


GATES = (
    "NOT_WEAK",
    "BREADTH_POS",
    "BREADTH5_POS",
    "MONEY_POS",
    "BREADTH_AND_MONEY",
    "BREADTH5_AND_MONEY",
    "STRONG_ALL",
)


def _period_metrics(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    all_s, all_l = v43._slice(series, ledger, None, None)
    dev_s, dev_l = v43._slice(series, ledger, None, v43.OOS_START - pd.Timedelta(days=1))
    oos_s, oos_l = v43._slice(series, ledger, v43.OOS_START, None)
    return {
        "all": v43._metrics(all_s, all_l),
        "development_2021_2023": v43._metrics(dev_s, dev_l),
        "oos_2024_2026": v43._metrics(oos_s, oos_l),
    }


def _evaluate(
    features: pd.DataFrame,
    all_dates: list[pd.Timestamp],
    gate: str,
    top_n: int,
    exit_label: str,
    cost_name: str,
) -> dict[str, Any]:
    mask = (
        features["base_executable"]
        & features["limit_gap"].ge(LIMIT_BUFFER)
        & _gate_mask(features, gate)
    )
    y = features.loc[mask].copy()
    y["score"] = y["clean_mom20_rank"].fillna(-np.inf)
    selected = v43._select_top(y, top_n)
    series, ledger = v43._portfolio_series(selected, all_dates, exit_label, cost_name)
    metrics = _period_metrics(series, ledger)
    return {
        "gate": gate,
        "top_n": top_n,
        "limit_buffer": LIMIT_BUFFER,
        "exit": exit_label,
        "cost": cost_name,
        "eligible_dates": int(y["trade_date"].nunique()),
        "selected_trade_rows": int(len(ledger)),
        "metrics": metrics,
    }


def _robustness(item: dict[str, Any]) -> dict[str, Any]:
    m = item["metrics"]
    allm = m["all"]
    dev = m["development_2021_2023"]
    oos = m["oos_2024_2026"]
    yrs = allm.get("yearly_returns", {})
    pos_years = sum(float(v) > 0 for v in yrs.values())
    return {
        "positive_years": int(pos_years),
        "total_years": int(len(yrs)),
        "full_cagr_positive": (allm.get("cagr") or -999) > 0,
        "dev_cagr_positive": (dev.get("cagr") or -999) > 0,
        "oos_cagr_positive": (oos.get("cagr") or -999) > 0,
        "full_maxdd_better_than_35pct": (allm.get("max_drawdown") or -1) > -0.35,
    }


def run() -> dict[str, Any]:
    candidates, all_dates = v43._prepare_candidates()
    minute = v43._minute_extract(candidates)
    features = v43._add_intraday_features(candidates, minute)

    if features["base_executable"].any():
        first_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].min())
        last_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].max())
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]

    results = []
    for gate in GATES:
        for top_n in TOP_NS:
            for exit_label in EXITS:
                for cost_name in COSTS:
                    item = _evaluate(features, all_dates, gate, top_n, exit_label, cost_name)
                    item["robustness"] = _robustness(item)
                    results.append(item)

    base = [x for x in results if x["cost"] == "BASE"]
    full_leaderboard = sorted(
        base,
        key=lambda x: x["metrics"]["all"].get("cagr")
        if x["metrics"]["all"].get("cagr") is not None else -999,
        reverse=True,
    )[:20]
    oos_leaderboard = sorted(
        base,
        key=lambda x: x["metrics"]["oos_2024_2026"].get("cagr")
        if x["metrics"]["oos_2024_2026"].get("cagr") is not None else -999,
        reverse=True,
    )[:20]

    conservative_lookup = {
        (x["gate"], x["top_n"], x["exit"]): x
        for x in results if x["cost"] == "CONSERVATIVE"
    }
    paired_top = []
    for x in full_leaderboard[:10]:
        key = (x["gate"], x["top_n"], x["exit"])
        paired_top.append({
            "base": x,
            "conservative": conservative_lookup.get(key),
        })

    report = {
        "question": "Can a causal T-1 market-state gate turn recent V4.3 profitability into a regime-robust full-history strategy?",
        "constraints": {
            "no_date_gate": True,
            "signal": "LIMIT_ADJUSTED_MOMENTUM from T-1",
            "rank": "clean_mom20_rank only; no same-day confirmation",
            "limit_buffer": LIMIT_BUFFER,
            "gates": list(GATES),
            "top_n": list(TOP_NS),
            "exits": list(EXITS),
            "costs": list(COSTS),
            "oos_start": str(v43.OOS_START.date()),
        },
        "coverage": {
            "candidate_rows": int(len(candidates)),
            "base_executable_rows": int(features["base_executable"].sum()),
            "base_executable_dates": int(features.loc[features["base_executable"], "trade_date"].nunique()),
        },
        "results": results,
        "full_history_leaderboard": full_leaderboard,
        "recent_oos_leaderboard": oos_leaderboard,
        "top_full_history_with_cost_stress": paired_top,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(json.dumps({
        "full_history_top5": full_leaderboard[:5],
        "recent_oos_top5": oos_leaderboard[:5],
        "top_with_cost_stress": paired_top[:3],
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
