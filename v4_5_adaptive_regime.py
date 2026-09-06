"""V4.5 causal adaptive regime switch for the long-only overnight strategy.

This is exploratory. It does NOT use a calendar/year cutoff. Instead it runs a
shadow version of each fixed base strategy and only deploys capital when the
strategy's own *previously realized* net returns indicate a favorable regime.

At trade date T, the return from the shadow trade opened on T-1 is already known
by T 10:00, before the new 14:45 decision. Every adaptive gate is shifted one
trade date so the current trade's outcome is never used in its own decision.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_5_adaptive_regime.json"
LIMIT_BUFFER = 0.005

BASES = (
    {"name": "B5_MONEY_TOP3_1000", "gate": "BREADTH5_AND_MONEY", "top_n": 3, "exit": "10:00"},
    {"name": "STRONG_ALL_TOP3_1000", "gate": "STRONG_ALL", "top_n": 3, "exit": "10:00"},
    {"name": "NOT_WEAK_TOP3_0935", "gate": "NOT_WEAK", "top_n": 3, "exit": "09:35"},
)
COSTS = ("BASE", "CONSERVATIVE")
ADAPTIVE_RULES = (
    "CAL60_POS",
    "CAL120_POS",
    "CAL180_POS",
    "CAL60_AND_120_POS",
    "ACTIVE20_POS",
    "ACTIVE40_POS",
    "ACTIVE60_POS",
    "ACTIVE20_AND_40_POS",
)


def _market_mask(x: pd.DataFrame, gate: str) -> pd.Series:
    weak = x["signal_weak_market"].fillna(True).astype(bool)
    breadth5 = x["breadth5"].fillna(-1.0)
    money = x["money_effect"].fillna(-1.0)
    if gate == "NOT_WEAK":
        return ~weak
    if gate == "BREADTH5_AND_MONEY":
        return (breadth5 > 0) & (money > 0)
    if gate == "STRONG_ALL":
        return (~weak) & (breadth5 > 0) & (money > 0)
    raise ValueError(gate)


def _shadow_strategy(
    features: pd.DataFrame,
    all_dates: list[pd.Timestamp],
    spec: dict[str, Any],
    cost_name: str,
) -> tuple[pd.Series, pd.DataFrame]:
    mask = (
        features["base_executable"]
        & features["limit_gap"].ge(LIMIT_BUFFER)
        & _market_mask(features, spec["gate"])
    )
    y = features.loc[mask].copy()
    y["score"] = y["clean_mom20_rank"].fillna(-np.inf)
    selected = v43._select_top(y, int(spec["top_n"]))
    return v43._portfolio_series(selected, all_dates, str(spec["exit"]), cost_name)


def _calendar_score(series: pd.Series, window: int) -> pd.Series:
    # Sum of log(1+r) gives the trailing compounded sign without numerical
    # underflow. Shift one trade date: T only sees outcomes through T-1.
    safe = series.clip(lower=-0.999999)
    score = np.log1p(safe).rolling(window, min_periods=window).sum()
    return score.shift(1)


def _active_score(series: pd.Series, window: int) -> pd.Series:
    active = series[series.ne(0)].copy()
    score = active.rolling(window, min_periods=window).mean().shift(1)
    out = pd.Series(np.nan, index=series.index, dtype=float)
    out.loc[score.index] = score
    # Only active candidate dates need a gate. Keep non-active dates NaN/false.
    return out


def _gate(series: pd.Series, rule: str) -> pd.Series:
    if rule == "CAL60_POS":
        return _calendar_score(series, 60) > 0
    if rule == "CAL120_POS":
        return _calendar_score(series, 120) > 0
    if rule == "CAL180_POS":
        return _calendar_score(series, 180) > 0
    if rule == "CAL60_AND_120_POS":
        return (_calendar_score(series, 60) > 0) & (_calendar_score(series, 120) > 0)
    if rule == "ACTIVE20_POS":
        return _active_score(series, 20) > 0
    if rule == "ACTIVE40_POS":
        return _active_score(series, 40) > 0
    if rule == "ACTIVE60_POS":
        return _active_score(series, 60) > 0
    if rule == "ACTIVE20_AND_40_POS":
        return (_active_score(series, 20) > 0) & (_active_score(series, 40) > 0)
    raise ValueError(rule)


def _period_metrics(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    all_s, all_l = v43._slice(series, ledger, None, None)
    dev_s, dev_l = v43._slice(series, ledger, None, v43.OOS_START - pd.Timedelta(days=1))
    oos_s, oos_l = v43._slice(series, ledger, v43.OOS_START, None)
    return {
        "all": v43._metrics(all_s, all_l),
        "development_2021_2023": v43._metrics(dev_s, dev_l),
        "oos_2024_2026": v43._metrics(oos_s, oos_l),
    }


def _apply_gate(
    shadow: pd.Series,
    ledger: pd.DataFrame,
    rule: str,
) -> tuple[pd.Series, pd.DataFrame, pd.Series]:
    g = _gate(shadow, rule).reindex(shadow.index, fill_value=False).fillna(False).astype(bool)
    live = shadow.where(g, 0.0)
    on_dates = set(pd.DatetimeIndex(g.index[g]))
    live_ledger = ledger[ledger["trade_date"].isin(on_dates)].copy()
    return live, live_ledger, g


def run() -> dict[str, Any]:
    candidates, all_dates = v43._prepare_candidates()
    minute = v43._minute_extract(candidates)
    features = v43._add_intraday_features(candidates, minute)
    if features["base_executable"].any():
        first_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].min())
        last_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].max())
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]

    rows: list[dict[str, Any]] = []
    bases_out: list[dict[str, Any]] = []
    for spec in BASES:
        for cost_name in COSTS:
            shadow, ledger = _shadow_strategy(features, all_dates, spec, cost_name)
            bases_out.append({
                "base": spec,
                "cost": cost_name,
                "metrics": _period_metrics(shadow, ledger),
            })
            for rule in ADAPTIVE_RULES:
                live, live_ledger, g = _apply_gate(shadow, ledger, rule)
                item = {
                    "base": spec,
                    "cost": cost_name,
                    "adaptive_rule": rule,
                    "gate_on_days": int(g.sum()),
                    "metrics": _period_metrics(live, live_ledger),
                }
                m = item["metrics"]
                yrs = m["all"].get("yearly_returns", {})
                item["robustness"] = {
                    "positive_years": int(sum(float(v) > 0 for v in yrs.values())),
                    "total_years": int(len(yrs)),
                    "all_cagr_positive": (m["all"].get("cagr") or -999) > 0,
                    "dev_cagr_positive": (m["development_2021_2023"].get("cagr") or -999) > 0,
                    "oos_cagr_positive": (m["oos_2024_2026"].get("cagr") or -999) > 0,
                    "maxdd_better_than_30pct": (m["all"].get("max_drawdown") or -1) > -0.30,
                }
                rows.append(item)

    base_cost = [x for x in rows if x["cost"] == "BASE"]
    robust = [
        x for x in base_cost
        if x["robustness"]["all_cagr_positive"]
        and x["robustness"]["dev_cagr_positive"]
        and x["robustness"]["oos_cagr_positive"]
    ]
    robust_sorted = sorted(
        robust,
        key=lambda x: x["metrics"]["all"].get("cagr") or -999,
        reverse=True,
    )
    full_sorted = sorted(
        base_cost,
        key=lambda x: x["metrics"]["all"].get("cagr") or -999,
        reverse=True,
    )

    cons_lookup = {
        (x["base"]["name"], x["adaptive_rule"]): x
        for x in rows if x["cost"] == "CONSERVATIVE"
    }
    top_pairs = []
    for x in (robust_sorted if robust_sorted else full_sorted)[:10]:
        key = (x["base"]["name"], x["adaptive_rule"])
        top_pairs.append({"base_cost": x, "conservative_cost": cons_lookup.get(key)})

    report = {
        "question": "Can a causal trailing-performance switch detect when the overnight long-only alpha is investable?",
        "warning": "Exploratory meta-filter. Parameters were proposed after observing the V4.3/V4.4 regime split; independent future validation is still required.",
        "causality": "Gate for trade T uses shadow strategy returns indexed through T-1 only; T-1 trade outcome is known by T morning before T 14:45 entry.",
        "base_specs": list(BASES),
        "adaptive_rules": list(ADAPTIVE_RULES),
        "limit_buffer": LIMIT_BUFFER,
        "base_strategies": bases_out,
        "results": rows,
        "robust_all_period_candidates": robust_sorted[:20],
        "full_history_leaderboard": full_sorted[:20],
        "top_candidates_with_cost_stress": top_pairs,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "robust_top5": robust_sorted[:5],
        "full_top5": full_sorted[:5],
        "top_cost_pairs": top_pairs[:3],
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
