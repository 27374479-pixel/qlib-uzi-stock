"""V4.9: book-native H02 panic-to-repair minute validation.

Source is frozen before results:
- Asking: in a weak market, only consider an extreme oversold rebound after
  index/theme/stock stop falling together; abandon if any layer keeps worsening.
- Yangjia: panic participation is an arbitrage-like exception; "others panic,
  I buy" requires collective market/theme panic rather than a single falling stock.
- BOOK_ALPHA_HYPOTHESIS_REGISTRY H02: collective panic -> breadth/theme/core repair.

This experiment does NOT invent a new price factor.  It keeps the old H02 daily
screen as context, moves the missing "synchronous repair" condition into causal
5-minute data, and compares it with a stock-only repair control from the same
panic context.

Daily setup T-1:
1) broad market is weak;
2) theme is in one of two pre-registered semantic panic translations:
   a) DIVERGENCE: existing book-derived theme divergence state;
   b) NEGATIVE_MAJORITY: theme mean return < 0 and fewer than half constituents up;
3) stock had prior activity and remains top-quartile within its theme on T-1;
4) non-one-word and executable on T.

Intraday T:
1) at least one completed bar has market, theme and stock all below preclose;
2) stock repairs above VWAP;
3) SELECTED requires market, theme and stock to improve synchronously for one or
   two completed bars, with theme median no weaker than market median and stock
   no weaker than theme median;
4) CONTROL enters on stock repair while the full synchronous condition is absent;
5) execution is the next bar open, with 0/5/10-minute delay robustness.

No magnitude threshold is searched.  Zero, 50% majority, top quartile and the
existing divergence state are semantic/ordinal translations already present in
the book registry.  Development is 2021-2023; 2024-2026 is historical holdout.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43
import v4_8_book_native_reclaim_validation as v48
import v4_intraday_survivor_validation as base
import v4_survivor_wrapper as survivor

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_9_book_native_panic_repair.json"
CSV_OUTPUT = ROOT / "output" / "v4_9_book_native_panic_repair.csv"
TRADE_OUTPUT = ROOT / "output" / "v4_9_book_native_panic_repair_trades.csv"

DEV_END = v43.OOS_START - pd.Timedelta(days=1)
MAX_POSITIONS = 3
COSTS = ("BASE", "CONSERVATIVE")
DELAYS = (0, 1, 2)
PANIC_VARIANTS = ("DIVERGENCE", "NEGATIVE_MAJORITY")
SYNC_BARS = (1, 2)
EXITS = ("OPEN", "10:00")


def _next_map(frame: pd.DataFrame) -> dict[pd.Timestamp, pd.Timestamp]:
    dates = sorted(pd.to_datetime(frame["date"]).dt.normalize().drop_duplicates())
    return {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}


def _daily_context() -> tuple[pd.DataFrame, pd.DataFrame, list[pd.Timestamp]]:
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
    prior_active = prior_touch.fillna(0).gt(0) | prior_seal.fillna(0).gt(0)

    one_word = frame["one_word"].fillna(False).astype(bool) if "one_word" in frame else pd.Series(False, index=frame.index)
    weak_market = frame["weak_market"].fillna(False).astype(bool)
    ret_rank = pd.to_numeric(frame["ret_rank"], errors="coerce")
    divergence = frame["divergence"].fillna(False).astype(bool)
    cohort_return = pd.to_numeric(frame["cohort_return"], errors="coerce")
    positive_ratio = pd.to_numeric(frame["positive_ratio"], errors="coerce")

    survivor_mask = prior_active & ret_rank.ge(0.75) & ~one_word & weak_market
    panic_masks = {
        "DIVERGENCE": divergence,
        "NEGATIVE_MAJORITY": cohort_return.lt(0) & positive_ratio.lt(0.50),
    }

    keep = [
        "date", "instrument", "close", "industry_code", "ret_rank",
        "cohort_return", "positive_ratio", "broken_ratio", "divergence",
        "breadth", "breadth5", "money_effect", "weak_market",
    ]
    parts: list[pd.DataFrame] = []
    for variant, theme_panic in panic_masks.items():
        x = frame.loc[survivor_mask & theme_panic, keep].copy()
        x["panic_variant"] = variant
        x = x.rename(columns={
            "date": "setup_date",
            "close": "previous_close",
            "industry_code": "setup_industry_code",
        })
        x["trade_date"] = x["setup_date"].map(nxt)
        x["exit_date"] = x["trade_date"].map(nxt)
        parts.append(x)

    if not parts:
        return pd.DataFrame(), pd.DataFrame(), []
    cand = pd.concat(parts, ignore_index=True).dropna(subset=["trade_date", "exit_date"])
    cand["trade_date"] = pd.to_datetime(cand["trade_date"]).dt.normalize()
    cand["exit_date"] = pd.to_datetime(cand["exit_date"]).dt.normalize()
    cand = cand[cand["trade_date"] >= v43.SAMPLE_START].copy()
    cand = cand[~cand["instrument"].astype(str).str.upper().str.startswith("SH688")].copy()

    exec_cols = ["date", "instrument", "upper_limit", "lower_limit", "industry_code"]
    for optional in ("trade_status", "is_st"):
        if optional in frame.columns:
            exec_cols.append(optional)
    exec_ref = frame[exec_cols].copy().rename(columns={
        "date": "trade_date",
        "upper_limit": "entry_upper_limit",
        "lower_limit": "entry_lower_limit",
        "industry_code": "trade_industry_code",
    })
    exec_ref["trade_date"] = pd.to_datetime(exec_ref["trade_date"]).dt.normalize()
    exec_ref = exec_ref.drop_duplicates(["trade_date", "instrument"], keep="last")
    cand = cand.merge(exec_ref, on=["trade_date", "instrument"], how="left", validate="many_to_one")
    if "trade_status" in cand.columns:
        cand = cand[cand["trade_status"].fillna(0).eq(1)]
    if "is_st" in cand.columns:
        cand = cand[cand["is_st"].fillna(1).eq(0)]
    cand = cand.drop_duplicates(["panic_variant", "trade_date", "instrument"]).reset_index(drop=True)

    daily_ref = frame[["date", "instrument", "preclose", "industry_code"]].copy().rename(columns={"date": "trade_date"})
    daily_ref["trade_date"] = pd.to_datetime(daily_ref["trade_date"]).dt.normalize()
    daily_ref = daily_ref.drop_duplicates(["trade_date", "instrument"], keep="last")
    all_dates = [d for d in sorted(frame["date"].drop_duplicates()) if d >= v43.SAMPLE_START]
    return cand, daily_ref, all_dates


def _three_way_negative(row: pd.Series) -> bool:
    vals = (row.get("market_median_ret"), row.get("peer_median_ret"), row.get("intraday_ret"))
    return all(pd.notna(v) and float(v) < 0.0 for v in vals)


def _sync_improving(x: pd.DataFrame, pos: int, bars: int) -> bool:
    if pos < bars:
        return False
    for k in range(bars):
        cur = x.iloc[pos - k]
        prev = x.iloc[pos - k - 1]
        for col in ("market_median_ret", "peer_median_ret", "intraday_ret"):
            if pd.isna(cur.get(col)) or pd.isna(prev.get(col)) or not float(cur[col]) > float(prev[col]):
                return False
    row = x.iloc[pos]
    if pd.isna(row.get("peer_median_ret")) or pd.isna(row.get("market_median_ret")):
        return False
    if float(row["peer_median_ret"]) < float(row["market_median_ret"]):
        return False
    if float(row["intraday_ret"]) < float(row["peer_median_ret"]):
        return False
    return True


def _find_triggers(day: pd.DataFrame, sync_bars: int) -> tuple[int | None, int | None]:
    x = v48._add_vwap(day)
    if len(x) < 5:
        return None, None
    weakness_seen = False
    selected_pos: int | None = None
    control_pos: int | None = None
    for pos in range(1, len(x) - 1):
        row = x.iloc[pos]
        if pd.Timestamp(row["datetime"]).time() > pd.Timestamp("14:45").time():
            break
        if _three_way_negative(row):
            weakness_seen = True
        if not weakness_seen or pd.isna(row.get("vwap")):
            continue
        prev = x.iloc[pos - 1]
        stock_repair = (
            float(row["close"]) > float(row["vwap"])
            and pd.notna(row.get("intraday_ret")) and pd.notna(prev.get("intraday_ret"))
            and float(row["intraday_ret"]) > float(prev["intraday_ret"])
        )
        if not stock_repair:
            continue
        sync = _sync_improving(x, pos, sync_bars)
        if sync and selected_pos is None:
            selected_pos = pos
        elif not sync and control_pos is None:
            control_pos = pos
        if selected_pos is not None and control_pos is not None:
            break
    return selected_pos, control_pos


def _build_triggers(candidates: pd.DataFrame, minutes: pd.DataFrame) -> pd.DataFrame:
    groups = {
        (str(inst), pd.Timestamp(date)): g.sort_values("datetime").reset_index(drop=True)
        for (inst, date), g in minutes.groupby(["instrument", "trade_date"], sort=False)
    }
    rows: list[dict[str, Any]] = []
    for c in candidates.to_dict("records"):
        key = (str(c["instrument"]), pd.Timestamp(c["trade_date"]))
        day = groups.get(key)
        if day is None or day.empty:
            continue
        for sync_bars in SYNC_BARS:
            selected_pos, control_pos = _find_triggers(day, sync_bars)
            for arm, pos in (("SELECTED_SYNC", selected_pos), ("CONTROL_STOCK_ONLY", control_pos)):
                if pos is None:
                    continue
                for delay in DELAYS:
                    entry = v48._entry_from_trigger(day, pos, delay, float(c["entry_upper_limit"]))
                    if entry is None:
                        continue
                    dt, px = entry
                    rows.append({
                        "panic_variant": c["panic_variant"],
                        "sync_bars": sync_bars,
                        "arm": arm,
                        "delay_bars": delay,
                        "instrument": c["instrument"],
                        "setup_date": c["setup_date"],
                        "trade_date": c["trade_date"],
                        "exit_date": c["exit_date"],
                        "industry_code": c.get("trade_industry_code", c.get("setup_industry_code")),
                        "trigger_datetime": pd.Timestamp(day.iloc[pos]["datetime"]),
                        "entry_datetime": dt,
                        "entry_price": px,
                    })
    return pd.DataFrame(rows)


def _select_earliest(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades
    x = trades.sort_values(["trade_date", "entry_datetime", "instrument"]).copy()
    x["rank"] = x.groupby("trade_date").cumcount() + 1
    return x[x["rank"] <= MAX_POSITIONS].copy()


def _daily_series(selected: pd.DataFrame, cost: str, exit_label: str) -> tuple[pd.Series, pd.DataFrame]:
    if selected.empty:
        return pd.Series(dtype=float), selected.copy()
    x = selected.copy()
    exit_col = v43._exit_column(exit_label)
    x = x.dropna(subset=["entry_price", exit_col]).copy()
    x["net_return"] = v43._net_return(x["entry_price"], x[exit_col], x["exit_date"], cost)
    daily = x.groupby("trade_date")["net_return"].mean().sort_index()
    return daily, x


def _metrics_full(daily: pd.Series, ledger: pd.DataFrame, all_dates: list[pd.Timestamp]) -> dict[str, Any]:
    idx = pd.DatetimeIndex(all_dates)
    return v43._metrics(daily.reindex(idx, fill_value=0.0), ledger)


def _slice(daily: pd.Series, ledger: pd.DataFrame, all_dates: list[pd.Timestamp]) -> dict[str, Any]:
    periods = {
        "all": (None, None),
        "development_2021_2023": (None, DEV_END),
        "oos_2024_2026": (v43.OOS_START, None),
    }
    out: dict[str, Any] = {}
    for name, (lo, hi) in periods.items():
        d = daily
        l = ledger
        dates = all_dates
        if lo is not None:
            d = d[d.index >= lo]
            l = l[pd.to_datetime(l["trade_date"]) >= lo] if not l.empty else l
            dates = [x for x in dates if x >= lo]
        if hi is not None:
            d = d[d.index <= hi]
            l = l[pd.to_datetime(l["trade_date"]) <= hi] if not l.empty else l
            dates = [x for x in dates if x <= hi]
        out[name] = _metrics_full(d, l, dates)
    return out


def _paired(selected: pd.Series, control: pd.Series, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> dict[str, Any]:
    s, c = selected.copy(), control.copy()
    if start is not None:
        s, c = s[s.index >= start], c[c.index >= start]
    if end is not None:
        s, c = s[s.index <= end], c[c.index <= end]
    z = pd.concat([s.rename("selected"), c.rename("control")], axis=1, join="inner").dropna()
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
    candidates, daily_ref, all_dates = _daily_context()
    if candidates.empty:
        raise RuntimeError("no H02 daily candidates")
    minutes = v48._load_candidate_minutes(candidates, daily_ref)
    triggers = _build_triggers(candidates, minutes)
    triggers = v48._attach_exits(triggers)

    if not triggers.empty:
        first_exec = pd.Timestamp(triggers["trade_date"].min())
        last_exec = pd.Timestamp(triggers["trade_date"].max())
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]

    results: list[dict[str, Any]] = []
    ledgers: list[pd.DataFrame] = []
    promotion_cells: list[dict[str, Any]] = []
    for panic_variant in PANIC_VARIANTS:
        for sync_bars in SYNC_BARS:
            for delay in DELAYS:
                cell = triggers[
                    triggers["panic_variant"].eq(panic_variant)
                    & triggers["sync_bars"].eq(sync_bars)
                    & triggers["delay_bars"].eq(delay)
                ].copy()
                arm_daily: dict[tuple[str, str, str], pd.Series] = {}
                arm_metrics: dict[tuple[str, str, str], dict[str, Any]] = {}
                for arm in ("SELECTED_SYNC", "CONTROL_STOCK_ONLY"):
                    selected = _select_earliest(cell[cell["arm"].eq(arm)].copy())
                    for exit_label in EXITS:
                        for cost in COSTS:
                            daily, ledger = _daily_series(selected, cost, exit_label)
                            metrics = _slice(daily, ledger, all_dates)
                            arm_daily[(arm, exit_label, cost)] = daily
                            arm_metrics[(arm, exit_label, cost)] = metrics
                            results.append({
                                "panic_variant": panic_variant,
                                "sync_bars": sync_bars,
                                "delay_bars": delay,
                                "arm": arm,
                                "exit": exit_label,
                                "cost": cost,
                                "metrics": metrics,
                            })
                            if cost == "BASE" and exit_label == "10:00":
                                keep = ledger.copy()
                                keep["panic_variant"] = panic_variant
                                keep["sync_bars"] = sync_bars
                                keep["delay_bars"] = delay
                                keep["arm"] = arm
                                ledgers.append(keep)

                for exit_label in EXITS:
                    for cost in COSTS:
                        s = arm_daily.get(("SELECTED_SYNC", exit_label, cost), pd.Series(dtype=float))
                        c = arm_daily.get(("CONTROL_STOCK_ONLY", exit_label, cost), pd.Series(dtype=float))
                        pair = {
                            "all": _paired(s, c),
                            "development_2021_2023": _paired(s, c, end=DEV_END),
                            "oos_2024_2026": _paired(s, c, start=v43.OOS_START),
                        }
                        results.append({
                            "panic_variant": panic_variant,
                            "sync_bars": sync_bars,
                            "delay_bars": delay,
                            "arm": "PAIRED_SELECTED_MINUS_CONTROL",
                            "exit": exit_label,
                            "cost": cost,
                            "paired": pair,
                        })

                # Promotion is judged only on the fixed 10:00 exit and requires
                # both cost robustness and selected-vs-control improvement.
                base_m = arm_metrics.get(("SELECTED_SYNC", "10:00", "BASE"), {})
                cons_m = arm_metrics.get(("SELECTED_SYNC", "10:00", "CONSERVATIVE"), {})
                base_s = arm_daily.get(("SELECTED_SYNC", "10:00", "BASE"), pd.Series(dtype=float))
                base_c = arm_daily.get(("CONTROL_STOCK_ONLY", "10:00", "BASE"), pd.Series(dtype=float))
                pdev = _paired(base_s, base_c, end=DEV_END)
                poos = _paired(base_s, base_c, start=v43.OOS_START)
                promote = bool(
                    base_m.get("development_2021_2023", {}).get("cagr", -1) > 0
                    and base_m.get("oos_2024_2026", {}).get("cagr", -1) > 0
                    and cons_m.get("development_2021_2023", {}).get("cagr", -1) >= 0
                    and cons_m.get("oos_2024_2026", {}).get("cagr", -1) >= 0
                    and pdev.get("selected_minus_control", -1) > 0
                    and poos.get("selected_minus_control", -1) > 0
                    and pdev.get("paired_days", 0) >= 20
                    and poos.get("paired_days", 0) >= 20
                )
                promotion_cells.append({
                    "panic_variant": panic_variant,
                    "sync_bars": sync_bars,
                    "delay_bars": delay,
                    "promote": promote,
                    "base_dev_cagr": base_m.get("development_2021_2023", {}).get("cagr"),
                    "base_oos_cagr": base_m.get("oos_2024_2026", {}).get("cagr"),
                    "cons_dev_cagr": cons_m.get("development_2021_2023", {}).get("cagr"),
                    "cons_oos_cagr": cons_m.get("oos_2024_2026", {}).get("cagr"),
                    "paired_dev_diff": pdev.get("selected_minus_control"),
                    "paired_oos_diff": poos.get("selected_minus_control"),
                    "paired_dev_days": pdev.get("paired_days"),
                    "paired_oos_days": poos.get("paired_days"),
                })

    report = {
        "question": "Does book-native collective panic -> synchronous market/theme/core repair outperform stock-only repair and survive executable cost/timing stress?",
        "source_registry": {
            "H02": "BOOK_ALPHA_HYPOTHESIS_REGISTRY.md + Asking + Yangjia book-derived references",
            "daily_context": "weak market + theme panic + prior-active top-quartile survivor",
            "minute_trigger": "market/theme/stock all weak first, then synchronous repair",
            "control": "same panic context; stock repairs above VWAP without full synchronous market/theme confirmation",
        },
        "research_discipline": {
            "no_data_mined_positive_factor": True,
            "no_oos_selection": True,
            "no_threshold_search": True,
            "development": "2021-2023",
            "oos": "2024-2026 historical holdout",
            "entry": "completed trigger bar -> next bar open; +5m/+10m delay stress",
            "exit_primary": "T+1 10:00; OPEN is diagnostic",
            "promotion_rule": "positive dev+OOS BASE, nonnegative dev+OOS CONSERVATIVE, and positive paired selected-control differential in both periods with >=20 paired days",
        },
        "proxy_limitations": [
            "CSI industry_code is still a theme proxy rather than true point-in-time concept/event membership.",
            "Existing weak_market/divergence states are engineering translations of book language, not claimed literal author formulas.",
            "This validates a historical proxy of H02, not the private discretionary process of any trader.",
        ],
        "coverage": {
            "daily_candidate_rows": int(len(candidates)),
            "candidate_trade_dates": int(candidates["trade_date"].nunique()),
            "candidate_minute_rows": int(len(minutes)),
            "trigger_rows": int(len(triggers)),
            "trigger_trade_dates": int(triggers["trade_date"].nunique()) if not triggers.empty else 0,
            "by_panic_variant_candidate_dates": {
                v: int(candidates.loc[candidates["panic_variant"].eq(v), "trade_date"].nunique()) for v in PANIC_VARIANTS
            },
        },
        "promotion_cells": promotion_cells,
        "results": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    flat: list[dict[str, Any]] = []
    for r in results:
        if r["arm"] == "PAIRED_SELECTED_MINUS_CONTROL":
            for period, p in r["paired"].items():
                flat.append({
                    "panic_variant": r["panic_variant"], "sync_bars": r["sync_bars"], "delay_bars": r["delay_bars"],
                    "arm": r["arm"], "exit": r["exit"], "cost": r["cost"], "period": period,
                    "paired_days": p.get("paired_days"), "selected_minus_control": p.get("selected_minus_control"),
                    "selected_mean": p.get("selected_mean"), "control_mean": p.get("control_mean"), "pnl_corr": p.get("pnl_corr"),
                })
        else:
            for period, m in r["metrics"].items():
                flat.append({
                    "panic_variant": r["panic_variant"], "sync_bars": r["sync_bars"], "delay_bars": r["delay_bars"],
                    "arm": r["arm"], "exit": r["exit"], "cost": r["cost"], "period": period,
                    "cagr": m.get("cagr"), "max_drawdown": m.get("max_drawdown"), "sharpe": m.get("sharpe"),
                    "active_days": m.get("active_days"), "active_win_rate": m.get("active_win_rate"), "trade_rows": m.get("trade_rows"),
                })
    pd.DataFrame(flat).to_csv(CSV_OUTPUT, index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(TRADE_OUTPUT, index=False)

    print(json.dumps({"coverage": report["coverage"], "promotion_cells": promotion_cells}, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
