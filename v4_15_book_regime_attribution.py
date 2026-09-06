"""V4.15: book-native regime attribution for X02 LIMIT_ADJUSTED_MOMENTUM.

Research question
-----------------
Why does the same executable X02 seed lose in 2021-2023 but work strongly in
2024-2026?  This script does NOT invent a new stock alpha and does NOT optimize
thresholds.  It translates the book-derived market-state language into a frozen,
causal attribution layer and asks whether conditional X02 expectancy is stable.

Book provenance
---------------
.agents/skills/chaogu-yangjia/references/principles.md:
- 赚钱效应增强: follow main-line strong cores; confirmation/divergence continuation
  is allowed.
- 市场平衡: probe potential new themes; failed anticipation exits quickly.
- 恐慌效应增强: reduce frequency; only panic-repair style trades are appropriate.
- "environment determines the mode, not merely position size".

Engineering translation (not claimed as Yangjia's literal formula)
------------------------------------------------------------------
All state inputs are known at T-1 close.
PANIC:
    existing frozen weak_market == True.
PROFIT_EXPANDING:
    not PANIC, breadth5 > 0, money_effect > 0, AND both breadth5 and
    money_effect are improving versus the immediately prior trading day.
PROFIT_POSITIVE:
    not PANIC, breadth5 > 0, money_effect > 0, but not both improving.
BALANCE:
    all remaining non-PANIC dates.

Only signs, first differences, and the repo's already-frozen weak_market proxy are
used. There is no magnitude grid and no OOS-driven threshold choice.

Execution is frozen X02:
- signal after T-1 close;
- exclude STAR, ST/suspended via existing candidate pipeline;
- T 14:45 completed 5m close;
- >=0.5% below upper limit;
- rank clean_mom20_rank only;
- Top3 equal weight;
- T+1 10:00 exit;
- BASE and CONSERVATIVE costs.

The script also reports one-axis diagnostics (weak-market, breadth sign,
money-effect sign, and whether each is rising) so we can distinguish a genuine
book-state explanation from a coincidental composite state.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43
import v4_intraday_survivor_validation as base
import v4_survivor_wrapper as survivor

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_15_book_regime_attribution.json"
CSV_OUTPUT = ROOT / "output" / "v4_15_book_regime_attribution.csv"
DEV_END = v43.OOS_START - pd.Timedelta(days=1)
LIMIT_BUFFER = 0.005
EXIT = "10:00"
TOP_N = 3
COSTS = ("BASE", "CONSERVATIVE")
STATES = ("PANIC", "BALANCE", "PROFIT_POSITIVE", "PROFIT_EXPANDING")


def _period_metrics(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    all_s, all_l = v43._slice(series, ledger, None, None)
    dev_s, dev_l = v43._slice(series, ledger, None, DEV_END)
    oos_s, oos_l = v43._slice(series, ledger, v43.OOS_START, None)
    return {
        "all": v43._metrics(all_s, all_l),
        "development_2021_2023": v43._metrics(dev_s, dev_l),
        "oos_2024_2026": v43._metrics(oos_s, oos_l),
    }


def _market_calendar() -> pd.DataFrame:
    cfg = base.Config(start="2015-01-01", end="2026-09-03")
    frame = survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    required = ["date", "breadth", "breadth5", "money_effect", "weak_market"]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise RuntimeError(f"prepared frame missing regime fields: {missing}")
    m = frame[required].drop_duplicates("date", keep="last").sort_values("date").copy()
    m["prev_breadth5"] = m["breadth5"].shift(1)
    m["prev_money_effect"] = m["money_effect"].shift(1)
    m["breadth5_rising"] = m["breadth5"] > m["prev_breadth5"]
    m["money_effect_rising"] = m["money_effect"] > m["prev_money_effect"]
    panic = m["weak_market"].fillna(True).astype(bool)
    positive = m["breadth5"].fillna(0).gt(0) & m["money_effect"].fillna(0).gt(0)
    expanding = positive & m["breadth5_rising"].fillna(False) & m["money_effect_rising"].fillna(False)
    m["book_regime"] = np.select(
        [panic, (~panic) & expanding, (~panic) & positive],
        ["PANIC", "PROFIT_EXPANDING", "PROFIT_POSITIVE"],
        default="BALANCE",
    )
    m["breadth_sign"] = np.where(m["breadth5"].fillna(0).gt(0), "POS", "NONPOS")
    m["money_sign"] = np.where(m["money_effect"].fillna(0).gt(0), "POS", "NONPOS")
    m["breadth_direction"] = np.where(m["breadth5_rising"].fillna(False), "RISING", "NOT_RISING")
    m["money_direction"] = np.where(m["money_effect_rising"].fillna(False), "RISING", "NOT_RISING")
    m["weak_axis"] = np.where(panic, "WEAK", "NON_WEAK")
    return m.rename(columns={"date": "signal_date"})


def _prepare() -> tuple[pd.DataFrame, list[pd.Timestamp], pd.DataFrame]:
    candidates, all_dates = v43._prepare_candidates()
    market = _market_calendar()
    add_cols = [
        "signal_date", "book_regime", "weak_axis", "breadth_sign", "money_sign",
        "breadth_direction", "money_direction", "breadth5_rising", "money_effect_rising",
        "prev_breadth5", "prev_money_effect",
    ]
    # Existing candidate fields breadth/breadth5/money_effect/weak_market are retained;
    # the merge adds only lag/direction/state labels built from the full trading calendar.
    candidates = candidates.merge(market[add_cols], on="signal_date", how="left", validate="many_to_one")
    minute = v43._minute_extract(candidates)
    features = v43._add_intraday_features(candidates, minute)
    eligible = features[
        features["base_executable"]
        & features["limit_gap"].ge(LIMIT_BUFFER)
    ].copy()
    if not eligible.empty:
        lo = pd.Timestamp(eligible["trade_date"].min())
        hi = pd.Timestamp(eligible["trade_date"].max())
        all_dates = [d for d in all_dates if lo <= d <= hi]
    return eligible, all_dates, market


def _select(sample: pd.DataFrame, all_dates: list[pd.Timestamp], cost: str) -> tuple[dict[str, Any], pd.DataFrame, pd.Series]:
    if sample.empty:
        empty = sample.copy()
        series, ledger = v43._portfolio_series(empty, all_dates, EXIT, cost)
        return _period_metrics(series, ledger), ledger, series
    x = sample.copy()
    x["score"] = x["clean_mom20_rank"].fillna(-np.inf)
    picked = v43._select_top(x, TOP_N)
    series, ledger = v43._portfolio_series(picked, all_dates, EXIT, cost)
    return _period_metrics(series, ledger), ledger, series


def _date_share(market: pd.DataFrame, label_col: str, label: str, lo=None, hi=None) -> float | None:
    x = market.copy()
    if lo is not None:
        x = x[x["signal_date"] >= lo]
    if hi is not None:
        x = x[x["signal_date"] <= hi]
    if x.empty:
        return None
    return float(x[label_col].eq(label).mean())


def _evaluate_family(
    eligible: pd.DataFrame,
    all_dates: list[pd.Timestamp],
    market: pd.DataFrame,
    family: str,
    labels: list[str],
    flat: list[dict[str, Any]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label in labels:
        z = eligible[eligible[family].eq(label)].copy()
        out[label] = {
            "eligible_rows": int(len(z)),
            "eligible_dates": int(z["trade_date"].nunique()) if len(z) else 0,
            "calendar_share_dev": _date_share(market, family, label, hi=DEV_END),
            "calendar_share_oos": _date_share(market, family, label, lo=v43.OOS_START),
            "costs": {},
        }
        for cost in COSTS:
            metrics, _, _ = _select(z, all_dates, cost)
            out[label]["costs"][cost] = metrics
            for period, m in metrics.items():
                flat.append({
                    "family": family,
                    "label": label,
                    "cost": cost,
                    "period": period,
                    "cagr": m.get("cagr"),
                    "max_drawdown": m.get("max_drawdown"),
                    "sharpe": m.get("sharpe"),
                    "active_days": m.get("active_days"),
                    "active_win_rate": m.get("active_win_rate"),
                    "trade_rows": m.get("trade_rows"),
                })
    return out


def _predicted_state_pass(states: dict[str, Any]) -> dict[str, Any]:
    # Book-predicted state is fixed BEFORE reading results: PROFIT_EXPANDING.
    x = states.get("PROFIT_EXPANDING", {}).get("costs", {})
    cells = {}
    passed = True
    for cost in COSTS:
        dev = x.get(cost, {}).get("development_2021_2023", {})
        oos = x.get(cost, {}).get("oos_2024_2026", {})
        cell = {
            "dev_cagr": dev.get("cagr"),
            "oos_cagr": oos.get("cagr"),
            "dev_mdd": dev.get("max_drawdown"),
            "oos_mdd": oos.get("max_drawdown"),
            "dev_active_days": dev.get("active_days"),
            "oos_active_days": oos.get("active_days"),
        }
        cells[cost] = cell
        if (
            cell["dev_cagr"] is None or cell["dev_cagr"] <= 0
            or cell["oos_cagr"] is None or cell["oos_cagr"] <= 0
            or (cell["dev_active_days"] or 0) < 20
            or (cell["oos_active_days"] or 0) < 20
        ):
            passed = False
    return {
        "predicted_state": "PROFIT_EXPANDING",
        "rule": "Both BASE and CONSERVATIVE must have positive dev and OOS CAGR with >=20 active days in each period. No other state may be substituted after seeing results.",
        "cells": cells,
        "pass": bool(passed),
    }


def run() -> dict[str, Any]:
    eligible, all_dates, market = _prepare()
    flat: list[dict[str, Any]] = []

    state_results = _evaluate_family(eligible, all_dates, market, "book_regime", list(STATES), flat)
    axis_results = {
        "weak_axis": _evaluate_family(eligible, all_dates, market, "weak_axis", ["NON_WEAK", "WEAK"], flat),
        "breadth_sign": _evaluate_family(eligible, all_dates, market, "breadth_sign", ["POS", "NONPOS"], flat),
        "money_sign": _evaluate_family(eligible, all_dates, market, "money_sign", ["POS", "NONPOS"], flat),
        "breadth_direction": _evaluate_family(eligible, all_dates, market, "breadth_direction", ["RISING", "NOT_RISING"], flat),
        "money_direction": _evaluate_family(eligible, all_dates, market, "money_direction", ["RISING", "NOT_RISING"], flat),
    }

    # Frozen baseline without any market gate, for attribution reference.
    baseline = {}
    for cost in COSTS:
        m, _, _ = _select(eligible, all_dates, cost)
        baseline[cost] = m
        for period, pm in m.items():
            flat.append({
                "family": "BASELINE_NO_GATE", "label": "ALL", "cost": cost, "period": period,
                "cagr": pm.get("cagr"), "max_drawdown": pm.get("max_drawdown"),
                "sharpe": pm.get("sharpe"), "active_days": pm.get("active_days"),
                "active_win_rate": pm.get("active_win_rate"), "trade_rows": pm.get("trade_rows"),
            })

    predicted = _predicted_state_pass(state_results)

    report = {
        "question": "Can a book-derived market regime explain X02's 2021-2023 loss versus 2024-2026 strength without tuning stock alpha?",
        "source": {
            "reference": ".agents/skills/chaogu-yangjia/references/principles.md",
            "book_idea": "environment determines the trading mode: profit effect strengthening / balance / panic effect strengthening",
            "not_claimed": "The engineering state labels are not Yangjia's literal private formula.",
        },
        "frozen_translation": {
            "PANIC": "existing T-1 weak_market=True",
            "PROFIT_EXPANDING": "not panic; breadth5>0; money_effect>0; both breadth5 and money_effect improve vs prior trading day",
            "PROFIT_POSITIVE": "not panic; breadth5>0; money_effect>0; not both improving",
            "BALANCE": "remaining non-panic dates",
            "no_threshold_grid": True,
        },
        "execution": {
            "signal": "X02 LIMIT_ADJUSTED_MOMENTUM at T-1",
            "market_gate": "NONE for attribution; state itself is the only conditioning variable",
            "limit_buffer": LIMIT_BUFFER,
            "rank": "clean_mom20_rank",
            "top_n": TOP_N,
            "entry": "T 14:45 close",
            "exit": "T+1 10:00",
            "costs": list(COSTS),
        },
        "coverage": {
            "eligible_rows": int(len(eligible)),
            "eligible_dates": int(eligible["trade_date"].nunique()) if len(eligible) else 0,
            "calendar_dates": int(len(market)),
        },
        "baseline_no_gate": baseline,
        "book_regime_results": state_results,
        "axis_diagnostics": axis_results,
        "pre_registered_profit_expanding_test": predicted,
        "decision_rule": "Only the pre-registered PROFIT_EXPANDING state may be considered for a future book-derived overlay. If it fails, do not rescue it by selecting another historical state; use the attribution only to learn what remains unexplained.",
        "limitations": [
            "weak_market itself is an earlier engineering proxy with frozen thresholds; this experiment does not optimize them.",
            "breadth/money first-difference is a semantic translation of 'strengthening', not a quoted book formula.",
            "2024-2026 has been inspected in prior experiments and is historical holdout, not pristine future OOS.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(flat).to_csv(CSV_OUTPUT, index=False)
    print(json.dumps({
        "coverage": report["coverage"],
        "pre_registered_profit_expanding_test": predicted,
        "state_calendar_shares": {
            s: {
                "dev": state_results[s]["calendar_share_dev"],
                "oos": state_results[s]["calendar_share_oos"],
            } for s in STATES
        },
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
