"""V4.13: pre-registered book H09 board-stage x regime interaction audit.

This is NOT a rescue search for the failed V4.12 strategy. H09 was registered
before V4.12 and explicitly requires first/second/third+ board states to be
reported separately across market regimes rather than averaged together.

Source:
- BOOK_ALPHA_HYPOTHESIS_REGISTRY.md H09
- .agents/skills/lenghuchong-limitup/references/lenghuchong-limitup-principles.md

Frozen audit:
- start from the already-executed V4.12 SELECTED_SUPPORT ledgers only;
- board stage is causal consecutive sealed-limit streak through signal day T-1
  plus the T reseal: FIRST=1, SECOND=2, THIRD_PLUS>=3;
- market regime is only the already-frozen T-1 weak_market flag:
  NON_WEAK vs WEAK;
- no stage threshold, return cutoff, or regime threshold is optimized;
- report both V4.12 execution delays (next bar and +5m) and BASE/CONSERVATIVE;
- fixed exit remains T+1 10:00.

A cell can only be marked HISTORICAL_FORWARD_CANDIDATE if the SAME stage x
regime is positive in 2021-2023 and 2024-2026 under both costs and both timing
delays, with >=20 active days in each period for each delay. Because the data
have already been observed in prior research, such a cell is not a final PASS;
it would require independent forward validation.
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
INPUT = ROOT / "output" / "v4_12_book_lenghuchong_reseal_trades.csv"
OUTPUT = ROOT / "output" / "v4_13_book_h09_board_stage_interaction.json"
CSV_OUTPUT = ROOT / "output" / "v4_13_book_h09_board_stage_interaction.csv"
DEV_END = v43.OOS_START - pd.Timedelta(days=1)
STAGES = ("FIRST", "SECOND", "THIRD_PLUS")
REGIMES = ("NON_WEAK", "WEAK")
DELAYS = (0, 1)
COSTS = ("BASE", "CONSERVATIVE")


def _consecutive_true(s: pd.Series) -> pd.Series:
    vals = s.fillna(False).astype(bool).to_numpy()
    out = np.zeros(len(vals), dtype=np.int16)
    run = 0
    for i, flag in enumerate(vals):
        run = run + 1 if flag else 0
        out[i] = run
    return pd.Series(out, index=s.index)


def _daily_context() -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    cfg = base.Config(start="2015-01-01", end="2026-09-03")
    frame = survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.sort_values(["instrument", "date"]).reset_index(drop=True)
    frame["seal_streak"] = frame.groupby("instrument", sort=False)["seal_up"].transform(_consecutive_true)
    context = frame[["date", "instrument", "seal_streak", "weak_market", "breadth5", "money_effect"]].copy()
    context = context.rename(columns={"date": "signal_date"})
    all_dates = [d for d in sorted(frame["date"].drop_duplicates()) if d >= v43.SAMPLE_START]
    return context, all_dates


def _stage(streak: pd.Series) -> pd.Series:
    n = pd.to_numeric(streak, errors="coerce").fillna(0).astype(int) + 1
    return pd.Series(np.where(n <= 1, "FIRST", np.where(n == 2, "SECOND", "THIRD_PLUS")), index=streak.index)


def _metrics_for(z: pd.DataFrame, all_dates: list[pd.Timestamp], cost: str) -> dict[str, Any]:
    if z.empty:
        daily = pd.Series(dtype=float)
        ledger = z.copy()
    else:
        ledger = z.dropna(subset=["entry_price", "exit_1000"]).copy()
        ledger["net_return_recalc"] = v43._net_return(
            pd.to_numeric(ledger["entry_price"], errors="coerce"),
            pd.to_numeric(ledger["exit_1000"], errors="coerce"),
            pd.to_datetime(ledger["exit_date"]),
            cost,
        )
        daily = ledger.groupby("trade_date")["net_return_recalc"].mean().sort_index()

    def one(lo: pd.Timestamp | None = None, hi: pd.Timestamp | None = None) -> dict[str, Any]:
        d = daily.copy()
        l = ledger.copy()
        dates = all_dates
        if lo is not None:
            d = d[d.index >= lo]
            l = l[pd.to_datetime(l["trade_date"]) >= lo] if not l.empty else l
            dates = [x for x in dates if x >= lo]
        if hi is not None:
            d = d[d.index <= hi]
            l = l[pd.to_datetime(l["trade_date"]) <= hi] if not l.empty else l
            dates = [x for x in dates if x <= hi]
        return v43._metrics(d.reindex(pd.DatetimeIndex(dates), fill_value=0.0), l)

    return {
        "all": one(),
        "development_2021_2023": one(hi=DEV_END),
        "oos_2024_2026": one(lo=v43.OOS_START),
    }


def run() -> dict[str, Any]:
    if not INPUT.exists():
        raise FileNotFoundError(f"missing prerequisite {INPUT}")
    trades = pd.read_csv(INPUT, parse_dates=["signal_date", "trade_date", "exit_date", "trigger_datetime", "entry_datetime"])
    trades = trades[trades["arm"].eq("SELECTED_SUPPORT")].copy()
    context, all_dates = _daily_context()
    trades = trades.merge(context, on=["signal_date", "instrument"], how="left", validate="many_to_one")
    if trades["weak_market"].isna().any():
        raise RuntimeError("missing T-1 regime context for some V4.12 trades")
    trades["board_stage"] = _stage(trades["seal_streak"])
    trades["regime"] = np.where(trades["weak_market"].astype(bool), "WEAK", "NON_WEAK")
    trades["trade_date"] = pd.to_datetime(trades["trade_date"]).dt.normalize()
    trades["exit_date"] = pd.to_datetime(trades["exit_date"]).dt.normalize()

    if not trades.empty:
        lo, hi = trades["trade_date"].min(), trades["trade_date"].max()
        all_dates = [d for d in all_dates if lo <= d <= hi]

    results: list[dict[str, Any]] = []
    lookup: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for stage in STAGES:
        for regime in REGIMES:
            for delay in DELAYS:
                z = trades[
                    trades["board_stage"].eq(stage)
                    & trades["regime"].eq(regime)
                    & trades["delay_bars"].eq(delay)
                ].copy()
                for cost in COSTS:
                    m = _metrics_for(z, all_dates, cost)
                    item = {
                        "board_stage": stage,
                        "regime": regime,
                        "delay_bars": delay,
                        "cost": cost,
                        "trade_rows": int(len(z)),
                        "metrics": m,
                    }
                    results.append(item)
                    lookup[(stage, regime, delay, cost)] = item

    candidates = []
    for stage in STAGES:
        for regime in REGIMES:
            checks = []
            cells = []
            for delay in DELAYS:
                for cost in COSTS:
                    item = lookup[(stage, regime, delay, cost)]
                    dev = item["metrics"]["development_2021_2023"]
                    oos = item["metrics"]["oos_2024_2026"]
                    ok = bool(
                        (dev.get("active_days") or 0) >= 20
                        and (oos.get("active_days") or 0) >= 20
                        and (dev.get("cagr") if dev.get("cagr") is not None else -999) > 0
                        and (oos.get("cagr") if oos.get("cagr") is not None else -999) > 0
                    )
                    checks.append(ok)
                    cells.append({
                        "delay_bars": delay,
                        "cost": cost,
                        "dev_active_days": dev.get("active_days"),
                        "oos_active_days": oos.get("active_days"),
                        "dev_cagr": dev.get("cagr"),
                        "oos_cagr": oos.get("cagr"),
                        "dev_mdd": dev.get("max_drawdown"),
                        "oos_mdd": oos.get("max_drawdown"),
                    })
            candidates.append({
                "board_stage": stage,
                "regime": regime,
                "historical_forward_candidate": bool(all(checks)),
                "cells": cells,
            })

    stage_counts = (
        trades[["trade_date", "instrument", "board_stage", "regime"]]
        .drop_duplicates()
        .groupby(["board_stage", "regime"])
        .size()
        .to_dict()
    )
    report = {
        "question": "Does pre-registered H09 board-stage x regime interaction reveal a historically robust subfamily inside failed V4.12 supported reseals?",
        "source": {
            "H09": "BOOK_ALPHA_HYPOTHESIS_REGISTRY.md: board stage is a state, not a monotonic buy signal",
            "Lenghuchong": ".agents/skills/lenghuchong-limitup/references/lenghuchong-limitup-principles.md: first/second/third+ boards and weak/strong markets must be separated",
        },
        "discipline": {
            "post_v4_12_audit_but_pre_registered_interaction": True,
            "no_threshold_search": True,
            "board_stage": "consecutive seal_up streak through T-1 + current T reseal; FIRST/SECOND/THIRD_PLUS",
            "regime": "T-1 frozen weak_market only; NON_WEAK/WEAK",
            "execution": "reuse already-executed V4.12 SELECTED_SUPPORT trades; T+1 10:00 exit",
            "costs": list(COSTS),
            "delays": list(DELAYS),
            "promotion_status": "diagnostic only; even a robust historical cell requires independent forward validation",
        },
        "coverage": {
            "supported_trade_rows_including_delays": int(len(trades)),
            "unique_stock_dates": int(len(trades[["trade_date", "instrument"]].drop_duplicates())),
            "stage_regime_stock_dates": {f"{k[0]}|{k[1]}": int(v) for k, v in stage_counts.items()},
        },
        "historical_candidates": candidates,
        "results": results,
        "limitations": [
            "The same 2021-2026 sample has already been inspected in prior research; no cell can be called pristine OOS.",
            "seal_up from completed daily data is used only through T-1; current T reseal is defined causally from V4.12 minute bars.",
            "weak_market is an engineering translation of market atmosphere, not a literal book formula.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    flat = []
    for item in results:
        for period, m in item["metrics"].items():
            flat.append({
                "board_stage": item["board_stage"], "regime": item["regime"],
                "delay_bars": item["delay_bars"], "cost": item["cost"], "period": period,
                "trade_rows": item["trade_rows"], "active_days": m.get("active_days"),
                "cagr": m.get("cagr"), "max_drawdown": m.get("max_drawdown"),
                "sharpe": m.get("sharpe"), "active_win_rate": m.get("active_win_rate"),
            })
    pd.DataFrame(flat).to_csv(CSV_OUTPUT, index=False)
    print(json.dumps({"coverage": report["coverage"], "historical_candidates": candidates}, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
