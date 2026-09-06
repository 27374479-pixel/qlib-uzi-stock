"""V4.8: book-native minute setup validation for H16/H17.

Research source is frozen BEFORE looking at results:
- H16 low-open-reclaim: BOOK_ALPHA_HYPOTHESIS_REGISTRY.md
- H17 first-divergence-reclaim: BOOK_ALPHA_HYPOTHESIS_REGISTRY.md
- H03 climax avoidance is tested only as a veto overlay.

This module deliberately does NOT mine arbitrary price factors. It translates
book-derived event sequences into causal observations and asks whether the
sequence itself survives broad execution perturbations.

H16 sequence:
1) a qualified core proxy is already established at T-1 close;
2) T opens below T-1 close;
3) within the first hour, a completed 5m bar reclaims VWAP and/or T-1 close;
4) same-industry peers are at least as healthy as the market;
5) execute only at a later bar open.

H17 sequence:
1) an active core proxy is already established at T-1 close;
2) T experiences observable divergence: a completed bar is below VWAP and
   below the session open;
3) later, a completed bar actively reclaims VWAP and the previous bar high;
4) same-industry peers remain supportive;
5) execute only at a later bar open.

No magnitude threshold is optimized. The only variants are semantic
translations already implicit in the book registry (VWAP-only vs stricter
reclaim; with/without climax veto) and 0/5/10-minute execution delay robustness.
2021-2023 is development; 2024-2026 is untouched OOS. No OOS result selects a
variant.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43
import v4_intraday_survivor_validation as base
import v4_survivor_wrapper as survivor

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_8_book_native_reclaim_validation.json"
CSV_OUTPUT = ROOT / "output" / "v4_8_book_native_reclaim_validation.csv"
TRADE_OUTPUT = ROOT / "output" / "v4_8_book_native_reclaim_trades.csv"

DEV_END = v43.OOS_START - pd.Timedelta(days=1)
MAX_POSITIONS = 3
COSTS = ("BASE", "CONSERVATIVE")
DELAYS = (0, 1, 2)  # extra completed 5m bars after the first executable next bar
VETOES = (False, True)
H16_VARIANTS = ("VWAP", "VWAP_AND_PREVCLOSE")
H17_VARIANTS = ("VWAP_PREVHIGH",)


def _next_map(frame: pd.DataFrame) -> dict[pd.Timestamp, pd.Timestamp]:
    dates = sorted(pd.to_datetime(frame["date"]).dt.normalize().drop_duplicates())
    return {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}


def _daily_context() -> tuple[pd.DataFrame, pd.DataFrame, list[pd.Timestamp]]:
    cfg = base.Config(start="2015-01-01", end="2026-09-03")
    frame = survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    nxt = _next_map(frame)

    prior_touch = pd.to_numeric(frame["prior_touch20"], errors="coerce").fillna(0) if "prior_touch20" in frame else pd.Series(0.0, index=frame.index)
    prior_seal = pd.to_numeric(frame["prior_seal5"], errors="coerce").fillna(0) if "prior_seal5" in frame else pd.Series(0.0, index=frame.index)
    prior_active = prior_touch.gt(0) | prior_seal.gt(0)

    core = frame["core"].fillna(False).astype(bool) if "core" in frame else pd.Series(False, index=frame.index)
    one_word = frame["one_word"].fillna(False).astype(bool) if "one_word" in frame else pd.Series(False, index=frame.index)
    climax = frame["climax"].fillna(False).astype(bool) if "climax" in frame else pd.Series(False, index=frame.index)

    # Context proxies only. No role_score is used to rank trades.
    h16_mask = core & ~one_word
    h17_mask = core & prior_active & ~one_word

    signal_keep = [
        "date", "instrument", "close", "industry_code",
        "breadth", "breadth5", "money_effect", "weak_market",
    ]
    parts: list[pd.DataFrame] = []
    for setup, mask in (("H16_LOW_OPEN_RECLAIM", h16_mask), ("H17_FIRST_DIVERGENCE_RECLAIM", h17_mask)):
        x = frame.loc[mask, signal_keep].copy()
        x["setup"] = setup
        x["setup_climax"] = climax.loc[x.index].to_numpy(bool)
        x = x.rename(columns={"date": "setup_date", "close": "previous_close", "industry_code": "setup_industry_code"})
        x["trade_date"] = x["setup_date"].map(nxt)
        x["exit_date"] = x["trade_date"].map(nxt)
        parts.append(x)

    cand = pd.concat(parts, ignore_index=True).dropna(subset=["trade_date", "exit_date"])
    cand["trade_date"] = pd.to_datetime(cand["trade_date"]).dt.normalize()
    cand["exit_date"] = pd.to_datetime(cand["exit_date"]).dt.normalize()
    cand = cand[cand["trade_date"] >= v43.SAMPLE_START].copy()
    cand = cand[~cand["instrument"].astype(str).str.upper().str.startswith("SH688")].copy()

    # Execution state must come from T, not from the T-1 signal row.
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
    cand = cand.drop_duplicates(["setup", "trade_date", "instrument"]).reset_index(drop=True)

    # Point-in-time T reference for peer/market intraday context.
    ref = frame[["date", "instrument", "preclose", "industry_code"]].copy().rename(columns={"date": "trade_date"})
    ref["trade_date"] = pd.to_datetime(ref["trade_date"]).dt.normalize()
    ref = ref.drop_duplicates(["trade_date", "instrument"], keep="last")

    all_dates = [d for d in sorted(frame["date"].drop_duplicates()) if d >= v43.SAMPLE_START]
    return cand, ref, all_dates


def _load_candidate_minutes(candidates: pd.DataFrame, daily_ref: pd.DataFrame) -> pd.DataFrame:
    missing = [str(p) for p in v43.MINUTE_FILES if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing persisted minute files: {missing}")

    keys = candidates[["trade_date", "instrument"]].drop_duplicates().copy()
    files_sql = ",".join("'" + str(p.resolve()).replace("'", "''") + "'" for p in v43.MINUTE_FILES)
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.register("cand_keys", keys)
    con.register("daily_ref", daily_ref)

    query = f"""
    WITH allbars AS (
      SELECT
        m.instrument,
        m.datetime,
        CAST(m.datetime AS DATE) AS trade_date,
        m.open, m.high, m.low, m.close, m.volume, m.amount,
        r.preclose,
        r.industry_code,
        m.close / NULLIF(r.preclose, 0) - 1.0 AS intraday_ret
      FROM read_parquet([{files_sql}]) m
      JOIN daily_ref r
        ON r.instrument=m.instrument
       AND CAST(r.trade_date AS DATE)=CAST(m.datetime AS DATE)
    ),
    peer AS (
      SELECT datetime, industry_code,
             COUNT(*) AS peer_n,
             MEDIAN(intraday_ret) AS peer_median_ret,
             AVG(CASE WHEN intraday_ret>0 THEN 1.0 ELSE 0.0 END) AS peer_positive_ratio
      FROM allbars
      GROUP BY 1,2
    ),
    market AS (
      SELECT datetime, MEDIAN(intraday_ret) AS market_median_ret
      FROM allbars GROUP BY 1
    ),
    cbars AS (
      SELECT a.*
      FROM allbars a
      JOIN cand_keys c
        ON c.instrument=a.instrument
       AND CAST(c.trade_date AS DATE)=a.trade_date
    )
    SELECT c.*, p.peer_n, p.peer_median_ret, p.peer_positive_ratio, m.market_median_ret
    FROM cbars c
    LEFT JOIN peer p USING(datetime, industry_code)
    LEFT JOIN market m USING(datetime)
    ORDER BY instrument, trade_date, datetime
    """
    out = con.execute(query).df()
    con.close()
    if out.empty:
        return out
    out["datetime"] = pd.to_datetime(out["datetime"])
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    for col in ("open", "high", "low", "close", "volume", "amount", "preclose"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _add_vwap(day: pd.DataFrame) -> pd.DataFrame:
    x = day.sort_values("datetime").copy().reset_index(drop=True)
    amount = pd.to_numeric(x["amount"], errors="coerce").fillna(0.0)
    volume = pd.to_numeric(x["volume"], errors="coerce").fillna(0.0)
    raw = amount.cumsum() / volume.cumsum().replace(0, np.nan)
    typical = ((x["high"] + x["low"] + x["close"]) / 3.0).expanding().mean()
    plausible = raw.between(x["low"] * 0.8, x["high"] * 1.2)
    x["vwap"] = raw.where(plausible, typical)
    return x


def _peer_support(row: pd.Series) -> bool:
    return bool(
        pd.notna(row.get("peer_n")) and int(row["peer_n"]) >= 3
        and float(row.get("peer_positive_ratio", 0.0)) >= 0.5
        and pd.notna(row.get("peer_median_ret")) and pd.notna(row.get("market_median_ret"))
        and float(row["peer_median_ret"]) >= float(row["market_median_ret"])
    )


def _trigger_h16(day: pd.DataFrame, previous_close: float, variant: str) -> int | None:
    x = _add_vwap(day)
    if len(x) < 4 or not np.isfinite(previous_close) or previous_close <= 0:
        return None
    if float(x.iloc[0]["open"]) >= previous_close:
        return None
    for pos in range(0, min(len(x) - 1, 12)):
        row = x.iloc[pos]
        if not _peer_support(row):
            continue
        above_vwap = pd.notna(row["vwap"]) and float(row["close"]) > float(row["vwap"])
        above_prev = float(row["close"]) > previous_close
        if variant == "VWAP":
            reclaim = above_vwap
        elif variant == "VWAP_AND_PREVCLOSE":
            reclaim = above_vwap and above_prev
        else:
            raise ValueError(variant)
        if reclaim:
            return pos
    return None


def _trigger_h17(day: pd.DataFrame, previous_close: float, variant: str) -> int | None:
    x = _add_vwap(day)
    if len(x) < 5:
        return None
    day_open = float(x.iloc[0]["open"])
    divergence_seen = False
    for pos in range(1, min(len(x) - 1, 54)):
        row = x.iloc[pos]
        if pd.isna(row["vwap"]):
            continue
        if not divergence_seen and float(row["close"]) < float(row["vwap"]) and float(row["close"]) < day_open:
            divergence_seen = True
            continue
        if not divergence_seen:
            continue
        if not _peer_support(row):
            continue
        prev_high = float(x.iloc[pos - 1]["high"])
        if variant == "VWAP_PREVHIGH":
            reclaim = float(row["close"]) > float(row["vwap"]) and float(row["close"]) > prev_high
        else:
            raise ValueError(variant)
        if reclaim:
            return pos
    return None


def _entry_from_trigger(day: pd.DataFrame, trigger_pos: int, delay: int, upper_limit: float) -> tuple[pd.Timestamp, float] | None:
    x = day.sort_values("datetime").reset_index(drop=True)
    entry_pos = trigger_pos + 1 + delay
    if entry_pos >= len(x):
        return None
    row = x.iloc[entry_pos]
    price = float(row["open"])
    if not np.isfinite(price) or price <= 0:
        return None
    if np.isfinite(upper_limit) and price >= upper_limit - 0.011 and float(row["low"]) >= upper_limit - 0.011:
        return None
    return pd.Timestamp(row["datetime"]), price


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
        setup = c["setup"]
        variants = H16_VARIANTS if setup == "H16_LOW_OPEN_RECLAIM" else H17_VARIANTS
        for variant in variants:
            pos = _trigger_h16(day, float(c["previous_close"]), variant) if setup == "H16_LOW_OPEN_RECLAIM" else _trigger_h17(day, float(c["previous_close"]), variant)
            if pos is None:
                continue
            for delay in DELAYS:
                entry = _entry_from_trigger(day, pos, delay, float(c["entry_upper_limit"]))
                if entry is None:
                    continue
                dt, px = entry
                rows.append({
                    "setup": setup,
                    "variant": variant,
                    "delay_bars": delay,
                    "h03_climax_veto_candidate": bool(c["setup_climax"]),
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


def _attach_exits(triggers: pd.DataFrame) -> pd.DataFrame:
    if triggers.empty:
        return triggers
    keys = triggers[["trade_date", "exit_date", "instrument"]].drop_duplicates()
    exits = v43._minute_extract(keys)[[
        "trade_date", "exit_date", "instrument", "exit_open", "exit_0935", "exit_0940", "exit_0945", "exit_1000"
    ]]
    return triggers.merge(exits, on=["trade_date", "exit_date", "instrument"], how="left", validate="many_to_one")


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
    series = daily.reindex(idx, fill_value=0.0)
    return v43._metrics(series, ledger)


def _slice_metrics(daily: pd.Series, ledger: pd.DataFrame, all_dates: list[pd.Timestamp]) -> dict[str, Any]:
    dev_daily = daily[daily.index <= DEV_END]
    dev_ledger = ledger[pd.to_datetime(ledger["trade_date"]) <= DEV_END] if not ledger.empty else ledger
    oos_daily = daily[daily.index >= v43.OOS_START]
    oos_ledger = ledger[pd.to_datetime(ledger["trade_date"]) >= v43.OOS_START] if not ledger.empty else ledger
    dev_dates = [d for d in all_dates if d <= DEV_END]
    oos_dates = [d for d in all_dates if d >= v43.OOS_START]
    return {
        "all": _metrics_full(daily, ledger, all_dates),
        "development_2021_2023": _metrics_full(dev_daily, dev_ledger, dev_dates),
        "oos_2024_2026": _metrics_full(oos_daily, oos_ledger, oos_dates),
    }


def run() -> dict[str, Any]:
    candidates, daily_ref, all_dates = _daily_context()
    minutes = _load_candidate_minutes(candidates, daily_ref)
    triggers = _attach_exits(_build_triggers(candidates, minutes))

    # Do not dilute CAGR/exposure with dates after the persisted minute sample.
    if not triggers.empty:
        first_exec = pd.Timestamp(triggers["trade_date"].min())
        last_exec = pd.Timestamp(triggers["trade_date"].max())
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]
    elif not minutes.empty:
        first_exec = pd.Timestamp(minutes["trade_date"].min())
        last_exec = pd.Timestamp(minutes["trade_date"].max())
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]

    results: list[dict[str, Any]] = []
    ledgers: list[pd.DataFrame] = []
    for setup in ("H16_LOW_OPEN_RECLAIM", "H17_FIRST_DIVERGENCE_RECLAIM"):
        variants = H16_VARIANTS if setup.startswith("H16") else H17_VARIANTS
        for variant in variants:
            for veto in VETOES:
                for delay in DELAYS:
                    base_rows = triggers[
                        triggers["setup"].eq(setup)
                        & triggers["variant"].eq(variant)
                        & triggers["delay_bars"].eq(delay)
                    ].copy()
                    if veto:
                        base_rows = base_rows[~base_rows["h03_climax_veto_candidate"]].copy()
                    selected = _select_earliest(base_rows)
                    for exit_label in ("OPEN", "09:35", "10:00"):
                        for cost in COSTS:
                            daily, ledger = _daily_series(selected, cost, exit_label)
                            m = _slice_metrics(daily, ledger, all_dates)
                            name = f"{setup}|{variant}|VETO{int(veto)}|D{delay}|EXIT_{exit_label}"
                            results.append({
                                "name": name,
                                "setup": setup,
                                "variant": variant,
                                "h03_climax_veto": veto,
                                "delay_bars": delay,
                                "exit": exit_label,
                                "cost": cost,
                                "metrics": m,
                            })
                            if cost == "BASE" and exit_label == "10:00":
                                keep = ledger.copy()
                                keep["experiment"] = name
                                ledgers.append(keep)

    report = {
        "question": "Do book-derived low-open reclaim and first-divergence reclaim sequences have causal, executable alpha across broad timing perturbations?",
        "source_registry": {
            "H16": "BOOK_ALPHA_HYPOTHESIS_REGISTRY.md: low-open-reclaim / weak-to-strong / divergence support",
            "H17": "BOOK_ALPHA_HYPOTHESIS_REGISTRY.md: first-divergence-reclaim / Yangjia-Qiao-Nirvana cluster",
            "H03": "BOOK_ALPHA_HYPOTHESIS_REGISTRY.md: climax avoidance, used only as veto comparison",
        },
        "research_discipline": {
            "no_data_mined_positive_factors": True,
            "no_oos_selection": True,
            "candidate_ranking": "earliest completed causal trigger; no hand-weighted role_score ranking",
            "execution": "completed trigger bar -> later bar open; test immediate-next-bar plus 5m/10m extra delay",
            "development": "2021-2023",
            "oos": "2024-2026",
            "promotion_rule": "Do not promote from a single best cell. Require same-sign OOS, cost robustness, and no collapse under 5m/10m delayed entry.",
        },
        "proxy_limitations": [
            "The pre-existing daily 'core'/'climax' labels are engineering proxies distilled from book rules; they are not claimed to be literal book formulas.",
            "CSI industry_code is a theme proxy; a later version should use point-in-time concept/event membership when historical coverage is reliable.",
            "Peer support uses relative/ordinal conditions rather than optimized return thresholds.",
        ],
        "coverage": {
            "daily_candidate_rows": int(len(candidates)),
            "candidate_minute_rows": int(len(minutes)),
            "trigger_rows_before_top3": int(len(triggers)),
            "candidate_trade_dates": int(candidates["trade_date"].nunique()) if len(candidates) else 0,
        },
        "results": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    flat = []
    for r in results:
        for period, m in r["metrics"].items():
            flat.append({
                "name": r["name"], "setup": r["setup"], "variant": r["variant"],
                "h03_climax_veto": r["h03_climax_veto"], "delay_bars": r["delay_bars"],
                "exit": r["exit"], "cost": r["cost"], "period": period,
                "cagr": m.get("cagr"), "max_drawdown": m.get("max_drawdown"),
                "sharpe": m.get("sharpe"), "calmar": m.get("calmar"),
                "active_days": m.get("active_days"), "active_win_rate": m.get("active_win_rate"),
                "trade_rows": m.get("trade_rows"),
            })
    pd.DataFrame(flat).to_csv(CSV_OUTPUT, index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(TRADE_OUTPUT, index=False)

    primaries = [
        r for r in results
        if r["cost"] == "BASE" and r["exit"] == "10:00"
        and r["delay_bars"] in (0, 1, 2)
        and not r["h03_climax_veto"]
    ]
    print(json.dumps({
        "coverage": report["coverage"],
        "primary_views": [
            {
                "name": r["name"],
                "dev_cagr": r["metrics"]["development_2021_2023"].get("cagr"),
                "oos_cagr": r["metrics"]["oos_2024_2026"].get("cagr"),
                "oos_mdd": r["metrics"]["oos_2024_2026"].get("max_drawdown"),
            }
            for r in primaries
        ],
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
