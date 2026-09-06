"""V4.12: book-native Lenghuchong open-board -> reseal validation.

Source before data:
- .agents/skills/lenghuchong-limitup/references/lenghuchong-limitup-principles.md
- The book-derived mapping says a limit-up is a state, not a buy point; research
  should reconstruct ignition/touch, board break, acceptance/reseal, market
  atmosphere, sector attack, stock character and real executability.

Frozen event on trade day T:
1) stock had recent active evidence known at T-1 (touch/seal now or in prior window);
2) T first touches its point-in-time upper limit;
3) a later completed 5m bar breaks/open-board: low and close are below the limit;
4) a still later completed bar closes back at the upper limit (reseal);
5) SELECTED_SUPPORT requires at reseal time:
   - broad-market median return > 0;
   - industry median return >= market median;
   - at least half of industry peers positive;
   - peer set >=3.
   CONTROL_UNSUPPORTED is the same touch-break-reseal event without all support.
6) execute only at the next bar open if it is not locked at the upper limit.
   A locked next bar is explicitly unfilled, not a fictional board fill.
7) A-share T+1 exit: next session OPEN / 10:00; BASE + CONSERVATIVE costs.

No return-magnitude, volume-multiple or board-count threshold is optimized.
Market >0, peer majority, and relative peer>=market are semantic/ordinal
translations of 'market atmosphere + sector attack'.  Delay +5m is a robustness
check, not a cell-selection search.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import external_challenger_daily_screen as ext
import v4_3_long_only_portfolio as v43
import v4_8_book_native_reclaim_validation as v48
import v4_intraday_survivor_validation as base
import v4_survivor_wrapper as survivor

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_12_book_lenghuchong_reseal.json"
CSV_OUTPUT = ROOT / "output" / "v4_12_book_lenghuchong_reseal.csv"
TRADE_OUTPUT = ROOT / "output" / "v4_12_book_lenghuchong_reseal_trades.csv"
DEV_END = v43.OOS_START - pd.Timedelta(days=1)
MAX_POSITIONS = 3
DELAYS = (0, 1)
COSTS = ("BASE", "CONSERVATIVE")
EXITS = ("OPEN", "10:00")


def _next_map(frame: pd.DataFrame) -> dict[pd.Timestamp, pd.Timestamp]:
    dates = sorted(pd.to_datetime(frame["date"]).dt.normalize().drop_duplicates())
    return {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}


def _daily_context() -> tuple[pd.DataFrame, pd.DataFrame, list[pd.Timestamp], dict[str, Any]]:
    cfg = base.Config(start="2015-01-01", end="2026-09-03")
    frame = survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    nxt = _next_map(frame)

    prior_touch = pd.to_numeric(frame.get("prior_touch20", 0), errors="coerce")
    if not isinstance(prior_touch, pd.Series):
        prior_touch = pd.Series(float(prior_touch), index=frame.index)
    prior_seal = pd.to_numeric(frame.get("prior_seal5", 0), errors="coerce")
    if not isinstance(prior_seal, pd.Series):
        prior_seal = pd.Series(float(prior_seal), index=frame.index)
    touch_today = frame["touch_up"].fillna(False).astype(bool)
    seal_today = frame["seal_up"].fillna(False).astype(bool)
    one_word = frame["one_word"].fillna(False).astype(bool)
    recent_active = prior_touch.fillna(0).gt(0) | prior_seal.fillna(0).gt(0) | touch_today | seal_today
    mask = recent_active & ~one_word

    keep = ["date", "instrument", "ret20", "hit_count20", "industry_code"]
    x = frame.loc[mask, keep].copy()
    x = x.rename(columns={
        "date": "signal_date",
        "ret20": "signal_ret20",
        "hit_count20": "signal_hit_count20",
        "industry_code": "signal_industry_code",
    })
    x["trade_date"] = x["signal_date"].map(nxt)
    x["exit_date"] = x["trade_date"].map(nxt)
    x = x.dropna(subset=["trade_date", "exit_date"]).copy()
    x["trade_date"] = pd.to_datetime(x["trade_date"]).dt.normalize()
    x["exit_date"] = pd.to_datetime(x["exit_date"]).dt.normalize()
    x = x[x["trade_date"] >= v43.SAMPLE_START].copy()
    x = x[~x["instrument"].astype(str).str.upper().str.startswith("SH688")].copy()

    exec_cols = ["date", "instrument", "upper_limit", "lower_limit", "industry_code"]
    for optional in ("trade_status", "is_st"):
        if optional in frame.columns:
            exec_cols.append(optional)
    ref_exec = frame[exec_cols].copy().rename(columns={
        "date": "trade_date",
        "upper_limit": "entry_upper_limit",
        "lower_limit": "entry_lower_limit",
        "industry_code": "trade_industry_code",
    })
    ref_exec["trade_date"] = pd.to_datetime(ref_exec["trade_date"]).dt.normalize()
    ref_exec = ref_exec.drop_duplicates(["trade_date", "instrument"], keep="last")
    x = x.merge(ref_exec, on=["trade_date", "instrument"], how="left", validate="many_to_one")
    if "trade_status" in x.columns:
        x = x[x["trade_status"].fillna(0).eq(1)]
    if "is_st" in x.columns:
        x = x[x["is_st"].fillna(1).eq(0)]
    x = x.drop_duplicates(["trade_date", "instrument"]).reset_index(drop=True)

    daily_ref = frame[["date", "instrument", "preclose", "industry_code"]].copy().rename(columns={"date": "trade_date"})
    daily_ref["trade_date"] = pd.to_datetime(daily_ref["trade_date"]).dt.normalize()
    daily_ref = daily_ref.drop_duplicates(["trade_date", "instrument"], keep="last")

    # X02 independence audit: map T-1 X02 signals into trade day T.
    masks = ext.challenger_masks(frame)
    x02 = frame.loc[masks["X02_limit_adjusted_momentum"]["selected"].fillna(False), ["date", "instrument"]].copy()
    x02["trade_date"] = x02["date"].map(nxt)
    x02 = x02.dropna(subset=["trade_date"])
    x02_keys = set(zip(pd.to_datetime(x02["trade_date"]), x02["instrument"].astype(str)))
    meta = {"x02_trade_keys": x02_keys}

    all_dates = [d for d in sorted(frame["date"].drop_duplicates()) if d >= v43.SAMPLE_START]
    return x, daily_ref, all_dates, meta


def _support(row: pd.Series) -> bool:
    return bool(
        pd.notna(row.get("market_median_ret")) and float(row["market_median_ret"]) > 0.0
        and pd.notna(row.get("peer_n")) and int(row["peer_n"]) >= 3
        and pd.notna(row.get("peer_median_ret")) and float(row["peer_median_ret"]) >= float(row["market_median_ret"])
        and pd.notna(row.get("peer_positive_ratio")) and float(row["peer_positive_ratio"]) >= 0.5
    )


def _find_reseal(day: pd.DataFrame, upper: float) -> tuple[int | None, dict[str, Any]]:
    x = day.sort_values("datetime").reset_index(drop=True)
    if len(x) < 5 or not np.isfinite(upper) or upper <= 0:
        return None, {"reason": "invalid_day_or_limit"}
    tol = 0.011
    touched = False
    broken = False
    touch_pos = None
    break_pos = None
    for pos in range(len(x) - 1):
        row = x.iloc[pos]
        if not touched and float(row["high"]) >= upper - tol:
            touched = True
            touch_pos = pos
            continue
        if touched and not broken and float(row["low"]) < upper - tol and float(row["close"]) < upper - tol:
            broken = True
            break_pos = pos
            continue
        if broken and float(row["close"]) >= upper - tol:
            return pos, {
                "touch_pos": touch_pos,
                "break_pos": break_pos,
                "support": _support(row),
                "market_median_ret": float(row["market_median_ret"]) if pd.notna(row.get("market_median_ret")) else None,
                "peer_median_ret": float(row["peer_median_ret"]) if pd.notna(row.get("peer_median_ret")) else None,
                "peer_positive_ratio": float(row["peer_positive_ratio"]) if pd.notna(row.get("peer_positive_ratio")) else None,
                "peer_n": int(row["peer_n"]) if pd.notna(row.get("peer_n")) else None,
            }
    return None, {"reason": "no_touch_break_reseal"}


def _build_events(candidates: pd.DataFrame, minutes: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    groups = {
        (str(inst), pd.Timestamp(date)): g.sort_values("datetime").reset_index(drop=True)
        for (inst, date), g in minutes.groupby(["instrument", "trade_date"], sort=False)
    }
    rows: list[dict[str, Any]] = []
    rejects: dict[str, int] = {}
    for c in candidates.to_dict("records"):
        key = (str(c["instrument"]), pd.Timestamp(c["trade_date"]))
        day = groups.get(key)
        if day is None or day.empty:
            rejects["minute_missing"] = rejects.get("minute_missing", 0) + 1
            continue
        pos, details = _find_reseal(day, float(c["entry_upper_limit"]))
        if pos is None:
            reason = details.get("reason", "no_event")
            rejects[reason] = rejects.get(reason, 0) + 1
            continue
        for delay in DELAYS:
            entry = v48._entry_from_trigger(day, pos, delay, float(c["entry_upper_limit"]))
            if entry is None:
                rejects[f"unfilled_delay_{delay}"] = rejects.get(f"unfilled_delay_{delay}", 0) + 1
                continue
            dt, px = entry
            rows.append({
                "arm": "SELECTED_SUPPORT" if details["support"] else "CONTROL_UNSUPPORTED",
                "delay_bars": delay,
                "instrument": c["instrument"],
                "signal_date": c["signal_date"],
                "trade_date": c["trade_date"],
                "exit_date": c["exit_date"],
                "signal_ret20": c.get("signal_ret20"),
                "signal_hit_count20": c.get("signal_hit_count20"),
                "industry_code": c.get("trade_industry_code", c.get("signal_industry_code")),
                "trigger_datetime": pd.Timestamp(day.iloc[pos]["datetime"]),
                "entry_datetime": dt,
                "entry_price": px,
                **{k: v for k, v in details.items() if k != "support"},
            })
    return pd.DataFrame(rows), rejects


def _select_earliest(x: pd.DataFrame) -> pd.DataFrame:
    if x.empty:
        return x
    y = x.sort_values(["trade_date", "entry_datetime", "instrument"]).copy()
    y["rank"] = y.groupby("trade_date").cumcount() + 1
    return y[y["rank"] <= MAX_POSITIONS].copy()


def _daily(selected: pd.DataFrame, exit_label: str, cost: str) -> tuple[pd.Series, pd.DataFrame]:
    if selected.empty:
        return pd.Series(dtype=float), selected.copy()
    z = selected.copy()
    exit_col = v43._exit_column(exit_label)
    z = z.dropna(subset=["entry_price", exit_col]).copy()
    z["net_return"] = v43._net_return(z["entry_price"], z[exit_col], z["exit_date"], cost)
    return z.groupby("trade_date")["net_return"].mean().sort_index(), z


def _metrics(daily: pd.Series, ledger: pd.DataFrame, all_dates: list[pd.Timestamp], lo=None, hi=None) -> dict[str, Any]:
    d, l = daily.copy(), ledger.copy()
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


def _paired(s: pd.Series, c: pd.Series, lo=None, hi=None) -> dict[str, Any]:
    a, b = s.copy(), c.copy()
    if lo is not None:
        a, b = a[a.index >= lo], b[b.index >= lo]
    if hi is not None:
        a, b = a[a.index <= hi], b[b.index <= hi]
    z = pd.concat([a.rename("selected"), b.rename("control")], axis=1, join="inner").dropna()
    if z.empty:
        return {"paired_days": 0}
    diff = z["selected"] - z["control"]
    return {
        "paired_days": int(len(z)),
        "selected_mean": float(z["selected"].mean()),
        "control_mean": float(z["control"].mean()),
        "selected_minus_control": float(diff.mean()),
        "selected_win_fraction": float((diff > 0).mean()),
        "pnl_corr": float(z.corr().iloc[0, 1]) if len(z) >= 3 else None,
    }


def run() -> dict[str, Any]:
    candidates, daily_ref, all_dates, meta = _daily_context()
    minutes = v48._load_candidate_minutes(candidates, daily_ref)
    events, rejects = _build_events(candidates, minutes)
    events = v48._attach_exits(events)
    if not events.empty:
        lo, hi = pd.Timestamp(events["trade_date"].min()), pd.Timestamp(events["trade_date"].max())
        all_dates = [d for d in all_dates if lo <= d <= hi]

    results: list[dict[str, Any]] = []
    promotion_cells: list[dict[str, Any]] = []
    ledgers: list[pd.DataFrame] = []
    for delay in DELAYS:
        cell = events[events["delay_bars"].eq(delay)].copy()
        series: dict[tuple[str, str, str], pd.Series] = {}
        metrics: dict[tuple[str, str, str], dict[str, Any]] = {}
        for arm in ("SELECTED_SUPPORT", "CONTROL_UNSUPPORTED"):
            picked = _select_earliest(cell[cell["arm"].eq(arm)].copy())
            for exit_label in EXITS:
                for cost in COSTS:
                    d, l = _daily(picked, exit_label, cost)
                    m = {
                        "all": _metrics(d, l, all_dates),
                        "development_2021_2023": _metrics(d, l, all_dates, hi=DEV_END),
                        "oos_2024_2026": _metrics(d, l, all_dates, lo=v43.OOS_START),
                    }
                    series[(arm, exit_label, cost)] = d
                    metrics[(arm, exit_label, cost)] = m
                    results.append({"delay_bars": delay, "arm": arm, "exit": exit_label, "cost": cost, "metrics": m})
                    if exit_label == "10:00" and cost == "BASE":
                        q = l.copy(); q["arm"] = arm; q["delay_bars"] = delay; ledgers.append(q)
        for exit_label in EXITS:
            for cost in COSTS:
                s = series.get(("SELECTED_SUPPORT", exit_label, cost), pd.Series(dtype=float))
                c = series.get(("CONTROL_UNSUPPORTED", exit_label, cost), pd.Series(dtype=float))
                results.append({
                    "delay_bars": delay, "arm": "PAIRED_SELECTED_MINUS_CONTROL", "exit": exit_label, "cost": cost,
                    "paired": {
                        "all": _paired(s, c),
                        "development_2021_2023": _paired(s, c, hi=DEV_END),
                        "oos_2024_2026": _paired(s, c, lo=v43.OOS_START),
                    },
                })

        base_m = metrics.get(("SELECTED_SUPPORT", "10:00", "BASE"), {})
        cons_m = metrics.get(("SELECTED_SUPPORT", "10:00", "CONSERVATIVE"), {})
        ps = series.get(("SELECTED_SUPPORT", "10:00", "BASE"), pd.Series(dtype=float))
        pc = series.get(("CONTROL_UNSUPPORTED", "10:00", "BASE"), pd.Series(dtype=float))
        pdev, poos = _paired(ps, pc, hi=DEV_END), _paired(ps, pc, lo=v43.OOS_START)
        promote = bool(
            base_m.get("development_2021_2023", {}).get("cagr", -999) > 0
            and base_m.get("oos_2024_2026", {}).get("cagr", -999) > 0
            and cons_m.get("development_2021_2023", {}).get("cagr", -999) >= 0
            and cons_m.get("oos_2024_2026", {}).get("cagr", -999) >= 0
            and pdev.get("selected_minus_control", -1) > 0
            and poos.get("selected_minus_control", -1) > 0
            and pdev.get("paired_days", 0) >= 20
            and poos.get("paired_days", 0) >= 20
        )
        promotion_cells.append({
            "delay_bars": delay, "promote": promote,
            "base_dev_cagr": base_m.get("development_2021_2023", {}).get("cagr"),
            "base_oos_cagr": base_m.get("oos_2024_2026", {}).get("cagr"),
            "cons_dev_cagr": cons_m.get("development_2021_2023", {}).get("cagr"),
            "cons_oos_cagr": cons_m.get("oos_2024_2026", {}).get("cagr"),
            "paired_dev_days": pdev.get("paired_days"), "paired_dev_diff": pdev.get("selected_minus_control"),
            "paired_oos_days": poos.get("paired_days"), "paired_oos_diff": poos.get("selected_minus_control"),
        })

    event_keys = set(zip(pd.to_datetime(events["trade_date"]), events["instrument"].astype(str))) if not events.empty else set()
    x02_keys = meta["x02_trade_keys"]
    supported = events[events["arm"].eq("SELECTED_SUPPORT")].copy() if not events.empty else events
    supported_keys = set(zip(pd.to_datetime(supported["trade_date"]), supported["instrument"].astype(str))) if not supported.empty else set()
    independence = {
        "all_reseal_event_stock_dates": int(len(event_keys)),
        "supported_reseal_stock_dates": int(len(supported_keys)),
        "x02_stock_dates": int(len(x02_keys)),
        "supported_x02_overlap": int(len(supported_keys & x02_keys)),
        "supported_x02_row_jaccard": float(len(supported_keys & x02_keys) / len(supported_keys | x02_keys)) if (supported_keys | x02_keys) else None,
    }

    report = {
        "question": "Does Lenghuchong's book-derived touch -> open-board -> supported reseal event have executable T+1 alpha beyond unsupported reseals?",
        "source": {
            "book_reference": ".agents/skills/lenghuchong-limitup/references/lenghuchong-limitup-principles.md",
            "idea": "limit-up is a state, not a buy point; wait for market/sector/stock/timing confluence and executable confirmation",
        },
        "frozen_definition": {
            "candidate": "recent active evidence known at T-1; non-one-word",
            "event": "T upper-limit touch -> later bar breaks below limit -> later completed bar closes back at limit",
            "support": "market median>0; peer median>=market median; peer positive ratio>=50%; peer_n>=3",
            "entry": "next 5m bar open only if not locked at upper limit",
            "delay_stress": "+0/+5m",
            "exit_primary": "T+1 10:00; OPEN diagnostic",
            "no_threshold_search": True,
        },
        "coverage": {
            "daily_candidates": int(len(candidates)),
            "candidate_dates": int(candidates["trade_date"].nunique()) if len(candidates) else 0,
            "minute_rows": int(len(minutes)),
            "event_rows_including_delays": int(len(events)),
            "event_dates": int(events["trade_date"].nunique()) if not events.empty else 0,
            "selected_support_rows": int(events["arm"].eq("SELECTED_SUPPORT").sum()) if not events.empty else 0,
            "control_unsupported_rows": int(events["arm"].eq("CONTROL_UNSUPPORTED").sum()) if not events.empty else 0,
            "rejects": rejects,
        },
        "x02_independence": independence,
        "promotion_rule": "For fixed T+1 10:00 exit: selected BASE dev+OOS >0, CONS dev+OOS >=0, paired selected-control diff >0 in both with >=20 paired days; +5m cell must independently pass to call timing robust.",
        "promotion_cells": promotion_cells,
        "timing_robust_promotion": bool(all(x["promote"] for x in promotion_cells)) if promotion_cells else False,
        "results": results,
        "limitations": [
            "5m OHLCV cannot observe queue priority or order-book cancellation; next-bar locked states are therefore unfilled.",
            "CSI industry_code is a theme proxy, not true point-in-time concept/event membership.",
            "The 0.011 price tolerance is inherited from the repo's point-in-time limit-touch convention, not optimized here.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    flat: list[dict[str, Any]] = []
    for r in results:
        if r["arm"] == "PAIRED_SELECTED_MINUS_CONTROL":
            for period, p in r["paired"].items():
                flat.append({"delay_bars": r["delay_bars"], "arm": r["arm"], "exit": r["exit"], "cost": r["cost"], "period": period, **p})
        else:
            for period, m in r["metrics"].items():
                flat.append({
                    "delay_bars": r["delay_bars"], "arm": r["arm"], "exit": r["exit"], "cost": r["cost"], "period": period,
                    "cagr": m.get("cagr"), "max_drawdown": m.get("max_drawdown"), "sharpe": m.get("sharpe"),
                    "active_days": m.get("active_days"), "active_win_rate": m.get("active_win_rate"), "trade_rows": m.get("trade_rows"),
                })
    pd.DataFrame(flat).to_csv(CSV_OUTPUT, index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(TRADE_OUTPUT, index=False)
    print(json.dumps({
        "coverage": report["coverage"], "x02_independence": independence,
        "promotion_cells": promotion_cells, "timing_robust_promotion": report["timing_robust_promotion"]
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
