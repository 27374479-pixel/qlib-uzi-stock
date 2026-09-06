"""V4.14: book H12 capacity/liquidity + H20 concentration audit for X02.

This does not invent a new alpha. It stress-tests the only surviving executable
seed, LIMIT_ADJUSTED_MOMENTUM (X02), against two pre-registered book modules:

H12 capacity / supply:
- alpha should not exist only in the smallest / least-liquid names;
- use causal T-1 float-market-cap and amount ranks, split into ordinal terciles;
- run the SAME X02 ranking/execution inside each tercile, no bucket tuning.

H20 concentration on best role:
- compare the SAME eligible X02 set at Top1/Top3/Top5/Top10;
- do not select a Top-N from OOS; report return, drawdown and cost sensitivity.

Frozen executable context is the V4.4 best static specification already seen:
T-1 breadth5>0 & money_effect>0, 0.5% limit buffer, T 14:45 close entry,
T+1 10:00 exit, BASE/CONSERVATIVE costs. 2021-2023 and 2024-2026 are reported
separately. This is robustness diagnosis, not pristine final validation.
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
OUTPUT = ROOT / "output" / "v4_14_book_h12_h20_capacity_concentration.json"
CSV_OUTPUT = ROOT / "output" / "v4_14_book_h12_h20_capacity_concentration.csv"
DEV_END = v43.OOS_START - pd.Timedelta(days=1)
LIMIT_BUFFER = 0.005
EXIT = "10:00"
COSTS = ("BASE", "CONSERVATIVE")
CAP_BUCKETS = ("SMALL", "MID", "LARGE")
LIQ_BUCKETS = ("LOW", "MID", "HIGH")
TOP_NS = (1, 3, 5, 10)


def _period_metrics(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    all_s, all_l = v43._slice(series, ledger, None, None)
    dev_s, dev_l = v43._slice(series, ledger, None, DEV_END)
    oos_s, oos_l = v43._slice(series, ledger, v43.OOS_START, None)
    return {
        "all": v43._metrics(all_s, all_l),
        "development_2021_2023": v43._metrics(dev_s, dev_l),
        "oos_2024_2026": v43._metrics(oos_s, oos_l),
    }


def _tercile(rank: pd.Series, low: str, mid: str, high: str) -> pd.Series:
    r = pd.to_numeric(rank, errors="coerce")
    return pd.Series(np.where(r <= 1/3, low, np.where(r <= 2/3, mid, high)), index=rank.index).where(r.notna())


def _select(features: pd.DataFrame, all_dates: list[pd.Timestamp], top_n: int, cost: str) -> tuple[dict[str, Any], pd.DataFrame]:
    if features.empty:
        empty = pd.DataFrame(columns=features.columns)
        series, ledger = v43._portfolio_series(empty, all_dates, EXIT, cost)
        return _period_metrics(series, ledger), ledger
    y = features.copy()
    y["score"] = y["clean_mom20_rank"].fillna(-np.inf)
    picked = v43._select_top(y, top_n)
    series, ledger = v43._portfolio_series(picked, all_dates, EXIT, cost)
    return _period_metrics(series, ledger), ledger


def _prepare() -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    candidates, all_dates = v43._prepare_candidates()

    cfg = base.Config(start="2015-01-01", end="2026-09-03")
    frame = survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    required = ["float_market_cap_est", "amount"]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise RuntimeError(f"daily frame missing H12 fields: {missing}")
    extra = frame[["date", "instrument", "float_market_cap_est", "amount"]].copy().rename(columns={
        "date": "signal_date",
        "float_market_cap_est": "signal_float_market_cap",
        "amount": "signal_amount",
    })
    extra["signal_date"] = pd.to_datetime(extra["signal_date"]).dt.normalize()
    extra = extra.drop_duplicates(["signal_date", "instrument"], keep="last")
    candidates = candidates.merge(extra, on=["signal_date", "instrument"], how="left", validate="many_to_one")

    minute = v43._minute_extract(candidates)
    features = v43._add_intraday_features(candidates, minute)
    if features["base_executable"].any():
        lo = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].min())
        hi = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].max())
        all_dates = [d for d in all_dates if lo <= d <= hi]

    eligible = features[
        features["base_executable"]
        & features["limit_gap"].ge(LIMIT_BUFFER)
        & features["breadth5"].fillna(-1).gt(0)
        & features["money_effect"].fillna(-1).gt(0)
    ].copy()
    by_day = eligible.groupby("trade_date", sort=False)
    eligible["cap_rank"] = by_day["signal_float_market_cap"].rank(pct=True)
    eligible["liq_rank"] = by_day["signal_amount"].rank(pct=True)
    eligible["cap_bucket"] = _tercile(eligible["cap_rank"], "SMALL", "MID", "LARGE")
    eligible["liq_bucket"] = _tercile(eligible["liq_rank"], "LOW", "MID", "HIGH")
    return eligible, all_dates


def _broad_count(bucket_results: dict[str, dict[str, Any]], require_dev: bool) -> int:
    count = 0
    for bucket, costs in bucket_results.items():
        ok = True
        for cost in COSTS:
            m = costs[cost]
            oos = m["oos_2024_2026"].get("cagr")
            if oos is None or oos <= 0:
                ok = False
            if require_dev:
                dev = m["development_2021_2023"].get("cagr")
                if dev is None or dev <= 0:
                    ok = False
        if ok:
            count += 1
    return count


def run() -> dict[str, Any]:
    eligible, all_dates = _prepare()
    cap_results: dict[str, dict[str, Any]] = {}
    liq_results: dict[str, dict[str, Any]] = {}
    concentration: dict[str, dict[str, Any]] = {}
    flat: list[dict[str, Any]] = []

    for dimension, buckets, store in (
        ("CAP", CAP_BUCKETS, cap_results),
        ("LIQUIDITY", LIQ_BUCKETS, liq_results),
    ):
        col = "cap_bucket" if dimension == "CAP" else "liq_bucket"
        for bucket in buckets:
            z = eligible[eligible[col].eq(bucket)].copy()
            store[bucket] = {}
            for cost in COSTS:
                m, _ = _select(z, all_dates, 3, cost)
                store[bucket][cost] = m
                for period, pm in m.items():
                    flat.append({
                        "family": dimension, "bucket": bucket, "top_n": 3,
                        "cost": cost, "period": period,
                        "cagr": pm.get("cagr"), "max_drawdown": pm.get("max_drawdown"),
                        "sharpe": pm.get("sharpe"), "active_days": pm.get("active_days"),
                        "active_win_rate": pm.get("active_win_rate"), "trade_rows": pm.get("trade_rows"),
                    })

    baseline_ledgers = {}
    for top_n in TOP_NS:
        concentration[str(top_n)] = {}
        for cost in COSTS:
            m, ledger = _select(eligible, all_dates, top_n, cost)
            concentration[str(top_n)][cost] = m
            if top_n == 3 and cost == "BASE":
                baseline_ledgers["TOP3_BASE"] = ledger.copy()
            for period, pm in m.items():
                flat.append({
                    "family": "CONCENTRATION", "bucket": None, "top_n": top_n,
                    "cost": cost, "period": period,
                    "cagr": pm.get("cagr"), "max_drawdown": pm.get("max_drawdown"),
                    "sharpe": pm.get("sharpe"), "active_days": pm.get("active_days"),
                    "active_win_rate": pm.get("active_win_rate"), "trade_rows": pm.get("trade_rows"),
                })

    baseline_bucket_diagnostics: dict[str, Any] = {}
    ledger = baseline_ledgers.get("TOP3_BASE", pd.DataFrame())
    if not ledger.empty:
        for col in ("cap_bucket", "liq_bucket"):
            g = ledger.groupby(col, dropna=False)["net_return"].agg(["count", "mean"])
            total = max(1, int(len(ledger)))
            baseline_bucket_diagnostics[col] = {
                str(idx): {"rows": int(row["count"]), "row_share": float(row["count"] / total), "mean_trade_return": float(row["mean"])}
                for idx, row in g.iterrows()
            }

    cap_oos = _broad_count(cap_results, require_dev=False)
    cap_hist = _broad_count(cap_results, require_dev=True)
    liq_oos = _broad_count(liq_results, require_dev=False)
    liq_hist = _broad_count(liq_results, require_dev=True)

    def delta(a_n: int, b_n: int, cost: str, period: str) -> dict[str, Any]:
        a = concentration[str(a_n)][cost][period]
        b = concentration[str(b_n)][cost][period]
        return {
            "cagr_delta": (a.get("cagr") - b.get("cagr")) if a.get("cagr") is not None and b.get("cagr") is not None else None,
            "mdd_delta": (a.get("max_drawdown") - b.get("max_drawdown")) if a.get("max_drawdown") is not None and b.get("max_drawdown") is not None else None,
        }

    report = {
        "question": "Is X02 robust across capacity/liquidity layers, and does concentration on Top1-3 outperform broader Top5-10 without hiding execution fragility?",
        "source": {
            "H12": "BOOK_ALPHA_HYPOTHESIS_REGISTRY.md: float-cap/liquidity interaction and real capacity",
            "H20": "BOOK_ALPHA_HYPOTHESIS_REGISTRY.md: concentration on best role versus pseudo-diversification",
        },
        "frozen_strategy": {
            "signal": "X02 LIMIT_ADJUSTED_MOMENTUM fixed at T-1",
            "market_gate": "T-1 breadth5>0 & money_effect>0",
            "limit_buffer": LIMIT_BUFFER,
            "rank": "clean_mom20_rank only",
            "entry": "T 14:45 close",
            "exit": "T+1 10:00",
            "costs": list(COSTS),
            "capacity_bins": "daily ordinal terciles among eligible X02 names using T-1 float_market_cap_est and T-1 amount; no optimized cutoffs",
        },
        "coverage": {
            "eligible_rows": int(len(eligible)),
            "eligible_dates": int(eligible["trade_date"].nunique()) if len(eligible) else 0,
            "cap_nonmissing": int(eligible["cap_bucket"].notna().sum()),
            "liq_nonmissing": int(eligible["liq_bucket"].notna().sum()),
        },
        "H12": {
            "cap_results": cap_results,
            "liquidity_results": liq_results,
            "cap_positive_oos_both_costs_buckets": cap_oos,
            "cap_positive_dev_and_oos_both_costs_buckets": cap_hist,
            "liquidity_positive_oos_both_costs_buckets": liq_oos,
            "liquidity_positive_dev_and_oos_both_costs_buckets": liq_hist,
            "recent_capacity_breadth_pass": bool(cap_oos >= 2 and liq_oos >= 2),
            "historical_capacity_breadth_pass": bool(cap_hist >= 2 and liq_hist >= 2),
            "top3_baseline_bucket_diagnostics": baseline_bucket_diagnostics,
        },
        "H20": {
            "concentration_results": concentration,
            "top3_minus_top5": {
                cost: {period: delta(3, 5, cost, period) for period in ("all", "development_2021_2023", "oos_2024_2026")}
                for cost in COSTS
            },
            "top3_minus_top10": {
                cost: {period: delta(3, 10, cost, period) for period in ("all", "development_2021_2023", "oos_2024_2026")}
                for cost in COSTS
            },
        },
        "limitations": [
            "Capacity buckets are relative terciles, not an institutional order-size market-impact model.",
            "T-1 daily amount measures observable liquidity before entry; it does not model queue depth at 14:45.",
            "2024-2026 has been inspected by prior experiments and remains historical holdout rather than pristine future OOS.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(flat).to_csv(CSV_OUTPUT, index=False)
    print(json.dumps({
        "coverage": report["coverage"],
        "H12_summary": {
            "cap_oos": cap_oos, "cap_hist": cap_hist,
            "liq_oos": liq_oos, "liq_hist": liq_hist,
            "recent_pass": report["H12"]["recent_capacity_breadth_pass"],
            "historical_pass": report["H12"]["historical_capacity_breadth_pass"],
        },
        "H20_top3_minus_top5": report["H20"]["top3_minus_top5"],
    }, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
