"""V4.16: book-derived capital-participation + theme-function attribution for X02.

This follows V4.15, where coarse profit/balance/panic states did NOT explain the
2021-2023 versus 2024-2026 sign flip. We therefore move one layer deeper in the
book logic rather than optimize market thresholds.

Book provenance
---------------
Chaogu Yangjia research proxy emphasizes, before chart shape:
- whether new money is still willing to enter;
- whether active/leader stocks still attract sustained capital;
- whether a core rise causes sector diffusion rather than isolated following;
- whether yesterday's active participants are making money.

Frozen engineering translations (all known at T-1 close)
---------------------------------------------------------
1) MARKET_AMOUNT_RISING:
   CSI800 total daily amount > immediately prior trading day.
2) ACTIVE_SHARE_RISING:
   share of CSI800 amount traded in currently/recently active names is rising.
   Active = current T-1 touch_up OR prior_touch20>0 OR prior_seal5>0.
3) THEME_SUPPORT for each X02 candidate:
   its T-1 industry cohort_return > 0 AND positive_ratio >= 50%.
   This is a majority/positive semantic proxy, not a tuned magnitude.
4) BOOK_CONFLUENCE (pre-registered predicted state):
   T-1 not weak_market; breadth5>0; money_effect>0;
   MARKET_AMOUNT_RISING; ACTIVE_SHARE_RISING; THEME_SUPPORT.

No threshold grid, no OOS-driven subset choice. All individual axes are reported
for attribution. Only BOOK_CONFLUENCE may be considered for later forward testing
if it independently has positive dev/OOS CAGR under BASE and CONSERVATIVE costs
with >=20 active days per period.

Execution remains frozen X02: 0.5% limit buffer, clean_mom20_rank Top3,
T 14:45 completed 5m close -> T+1 10:00.
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
OUTPUT = ROOT / "output" / "v4_16_book_capital_theme_attribution.json"
CSV_OUTPUT = ROOT / "output" / "v4_16_book_capital_theme_attribution.csv"
DEV_END = v43.OOS_START - pd.Timedelta(days=1)
LIMIT_BUFFER = 0.005
TOP_N = 3
EXIT = "10:00"
COSTS = ("BASE", "CONSERVATIVE")


def _period_metrics(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    all_s, all_l = v43._slice(series, ledger, None, None)
    dev_s, dev_l = v43._slice(series, ledger, None, DEV_END)
    oos_s, oos_l = v43._slice(series, ledger, v43.OOS_START, None)
    return {
        "all": v43._metrics(all_s, all_l),
        "development_2021_2023": v43._metrics(dev_s, dev_l),
        "oos_2024_2026": v43._metrics(oos_s, oos_l),
    }


def _prepare_daily_context() -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = base.Config(start="2015-01-01", end="2026-09-03")
    frame = survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    required = [
        "date", "instrument", "amount", "touch_up", "prior_touch20", "prior_seal5",
        "cohort_return", "positive_ratio", "weak_market", "breadth5", "money_effect",
    ]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise RuntimeError(f"prepared frame missing V4.16 fields: {missing}")

    amount = pd.to_numeric(frame["amount"], errors="coerce").fillna(0.0)
    active = (
        frame["touch_up"].fillna(False).astype(bool)
        | pd.to_numeric(frame["prior_touch20"], errors="coerce").fillna(0).gt(0)
        | pd.to_numeric(frame["prior_seal5"], errors="coerce").fillna(0).gt(0)
    )
    work = pd.DataFrame({"date": frame["date"], "amount": amount, "active_amount": amount.where(active, 0.0)})
    market = work.groupby("date", sort=True).agg(
        market_amount=("amount", "sum"),
        active_amount=("active_amount", "sum"),
    ).reset_index()
    market["active_amount_share"] = market["active_amount"] / market["market_amount"].replace(0, np.nan)
    market["prev_market_amount"] = market["market_amount"].shift(1)
    market["prev_active_amount_share"] = market["active_amount_share"].shift(1)
    market["market_amount_rising"] = market["market_amount"] > market["prev_market_amount"]
    market["active_share_rising"] = market["active_amount_share"] > market["prev_active_amount_share"]
    market = market.rename(columns={"date": "signal_date"})

    stock = frame[[
        "date", "instrument", "cohort_return", "positive_ratio",
        "weak_market", "breadth5", "money_effect",
    ]].copy().rename(columns={"date": "signal_date"})
    stock["theme_support"] = (
        pd.to_numeric(stock["cohort_return"], errors="coerce").gt(0)
        & pd.to_numeric(stock["positive_ratio"], errors="coerce").ge(0.5)
    )
    stock = stock.drop_duplicates(["signal_date", "instrument"], keep="last")
    return market, stock


def _prepare() -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    candidates, all_dates = v43._prepare_candidates()
    market, stock = _prepare_daily_context()
    candidates = candidates.merge(market, on="signal_date", how="left", validate="many_to_one")
    # v4_3 candidate already has weak/breadth/money; merge only theme fields to avoid suffix ambiguity.
    candidates = candidates.merge(
        stock[["signal_date", "instrument", "cohort_return", "positive_ratio", "theme_support"]],
        on=["signal_date", "instrument"], how="left", validate="many_to_one",
    )
    candidates["market_amount_axis"] = np.where(candidates["market_amount_rising"].fillna(False), "RISING", "NOT_RISING")
    candidates["active_share_axis"] = np.where(candidates["active_share_rising"].fillna(False), "RISING", "NOT_RISING")
    candidates["theme_axis"] = np.where(candidates["theme_support"].fillna(False), "SUPPORT", "NO_SUPPORT")
    candidates["book_confluence"] = (
        ~candidates["signal_weak_market"].fillna(True).astype(bool)
        & candidates["breadth5"].fillna(0).gt(0)
        & candidates["money_effect"].fillna(0).gt(0)
        & candidates["market_amount_rising"].fillna(False)
        & candidates["active_share_rising"].fillna(False)
        & candidates["theme_support"].fillna(False)
    )
    candidates["confluence_axis"] = np.where(candidates["book_confluence"], "CONFLUENT", "NOT_CONFLUENT")

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
    return eligible, all_dates


def _select(sample: pd.DataFrame, all_dates: list[pd.Timestamp], cost: str) -> tuple[dict[str, Any], pd.DataFrame]:
    x = sample.copy()
    if not x.empty:
        x["score"] = x["clean_mom20_rank"].fillna(-np.inf)
        x = v43._select_top(x, TOP_N)
    series, ledger = v43._portfolio_series(x, all_dates, EXIT, cost)
    return _period_metrics(series, ledger), ledger


def _evaluate(
    eligible: pd.DataFrame,
    all_dates: list[pd.Timestamp],
    col: str,
    labels: list[str],
    flat: list[dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label in labels:
        z = eligible[eligible[col].eq(label)].copy()
        result[label] = {
            "eligible_rows": int(len(z)),
            "eligible_dates": int(z["trade_date"].nunique()) if len(z) else 0,
            "costs": {},
        }
        for cost in COSTS:
            m, _ = _select(z, all_dates, cost)
            result[label]["costs"][cost] = m
            for period, pm in m.items():
                flat.append({
                    "family": col, "label": label, "cost": cost, "period": period,
                    "cagr": pm.get("cagr"), "max_drawdown": pm.get("max_drawdown"),
                    "sharpe": pm.get("sharpe"), "active_days": pm.get("active_days"),
                    "active_win_rate": pm.get("active_win_rate"), "trade_rows": pm.get("trade_rows"),
                })
    return result


def _promotion(confluence: dict[str, Any]) -> dict[str, Any]:
    cells = {}
    passed = True
    costs = confluence.get("CONFLUENT", {}).get("costs", {})
    for cost in COSTS:
        dev = costs.get(cost, {}).get("development_2021_2023", {})
        oos = costs.get(cost, {}).get("oos_2024_2026", {})
        cell = {
            "dev_cagr": dev.get("cagr"), "oos_cagr": oos.get("cagr"),
            "dev_mdd": dev.get("max_drawdown"), "oos_mdd": oos.get("max_drawdown"),
            "dev_active_days": dev.get("active_days"), "oos_active_days": oos.get("active_days"),
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
        "predicted_state": "CONFLUENT",
        "rule": "Both costs require positive dev+OOS CAGR and >=20 active days per period. No alternative historical combination may replace this state after results are seen.",
        "cells": cells,
        "pass": bool(passed),
    }


def run() -> dict[str, Any]:
    eligible, all_dates = _prepare()
    flat: list[dict[str, Any]] = []
    market_amount = _evaluate(eligible, all_dates, "market_amount_axis", ["RISING", "NOT_RISING"], flat)
    active_share = _evaluate(eligible, all_dates, "active_share_axis", ["RISING", "NOT_RISING"], flat)
    theme = _evaluate(eligible, all_dates, "theme_axis", ["SUPPORT", "NO_SUPPORT"], flat)
    confluence = _evaluate(eligible, all_dates, "confluence_axis", ["CONFLUENT", "NOT_CONFLUENT"], flat)
    predicted = _promotion(confluence)

    baseline = {}
    for cost in COSTS:
        m, _ = _select(eligible, all_dates, cost)
        baseline[cost] = m

    report = {
        "question": "Do capital participation and theme diffusion explain X02's structural break better than coarse market regime alone?",
        "source": {
            "reference": ".agents/skills/chaogu-yangjia/references/principles.md and .agents/skills/yangjia-trading/SKILL.md",
            "book_logic": "new money willingness + active-core participation + sector diffusion are prior to chart-shape selection",
            "not_claimed": "These are causal engineering proxies, not a literal private formula.",
        },
        "frozen_translation": {
            "MARKET_AMOUNT_RISING": "T-1 CSI800 total amount > prior trading day",
            "ACTIVE_SHARE_RISING": "T-1 amount share of current/recent active names > prior trading day",
            "THEME_SUPPORT": "T-1 candidate industry cohort_return>0 and positive_ratio>=50%",
            "BOOK_CONFLUENCE": "not weak; breadth5>0; money_effect>0; market amount rising; active amount share rising; theme support",
            "no_threshold_grid": True,
        },
        "execution": {
            "signal": "X02 LIMIT_ADJUSTED_MOMENTUM T-1",
            "limit_buffer": LIMIT_BUFFER, "rank": "clean_mom20_rank", "top_n": TOP_N,
            "entry": "T 14:45 close", "exit": "T+1 10:00", "costs": list(COSTS),
        },
        "coverage": {
            "eligible_rows": int(len(eligible)),
            "eligible_dates": int(eligible["trade_date"].nunique()) if len(eligible) else 0,
            "confluent_rows": int(eligible["book_confluence"].sum()) if len(eligible) else 0,
            "confluent_dates": int(eligible.loc[eligible["book_confluence"], "trade_date"].nunique()) if len(eligible) else 0,
        },
        "baseline_no_gate": baseline,
        "axis_results": {
            "market_amount": market_amount,
            "active_amount_share": active_share,
            "theme_support": theme,
        },
        "book_confluence_results": confluence,
        "pre_registered_confluence_test": predicted,
        "decision_rule": "If CONFLUENT fails, use axes only for attribution and do not assemble a new historical combination from whichever axes look best.",
        "limitations": [
            "CSI800 amount is a broad-market proxy, not all-A-share capital flow.",
            "Industry_code is a point-in-time industry proxy, not a true dynamic event/theme graph.",
            "Rising uses one-trading-day direction only; no magnitude is optimized.",
            "2024-2026 is historical holdout already inspected by prior experiments, not pristine future OOS.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(flat).to_csv(CSV_OUTPUT, index=False)
    print(json.dumps({"coverage": report["coverage"], "confluence_test": predicted}, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
