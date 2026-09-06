"""V4.3 long-only portfolio backtest for LIMIT_ADJUSTED_MOMENTUM.

Goal: turn the validated relative alpha into an executable A-share strategy:
- signal fixed after T-1 close;
- trade on T at the 14:45 bar close (causal for end-labelled 5m bars);
- exclude limit-up / near-limit / missing-liquidity names;
- optionally require frozen market regime and same-day intraday confirmation;
- buy Top-N equal-weight;
- sell next session at OPEN / 09:35 / 09:40 / 09:45 / 10:00;
- report continuous-account CAGR, max drawdown, Sharpe and yearly returns
  under explicit historical stamp duty, commissions and slippage.

The primary strategy is pre-registered in PRIMARY_SPEC. Sensitivity variants are
reported but are not allowed to redefine the primary result after seeing OOS.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import v4_intraday_survivor_validation as base
import v4_survivor_wrapper as survivor
from external_challenger_daily_screen import challenger_masks

ROOT = Path(__file__).resolve().parent
MINUTE_FILES = tuple(
    ROOT / "data_lake" / "raw" / "traderharness" / f"paired_ext_5min_{year}.parquet"
    for year in range(2021, 2027)
)
OUTPUT = ROOT / "output" / "v4_3_long_only_portfolio.json"
LEDGER = ROOT / "output" / "v4_3_primary_trade_ledger.csv"

SAMPLE_START = pd.Timestamp("2021-05-17")
OOS_START = pd.Timestamp("2024-01-01")
EXIT_LABELS = ("OPEN", "09:35", "09:40", "09:45", "10:00")

PRIMARY_SPEC = {
    "strategy": "PRIMARY",
    "market_gate": "NOT_WEAK",
    "rank_mode": "CONFIRM_COMBO",
    "top_n": 5,
    "limit_buffer": 0.005,
    "exit": "OPEN",
    "cost": "BASE",
}


@dataclass(frozen=True)
class CostSpec:
    commission_each_side: float
    slippage_each_side: float


COSTS = {
    "RAW": CostSpec(0.0, 0.0),
    "BASE": CostSpec(0.00025, 0.00050),
    "CONSERVATIVE": CostSpec(0.00030, 0.00100),
}


def _next_map(frame: pd.DataFrame) -> dict[pd.Timestamp, pd.Timestamp]:
    dates = sorted(pd.to_datetime(frame["date"]).dt.normalize().drop_duplicates())
    return {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}


def _prepare_candidates() -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    cfg = base.Config(start="2015-01-01", end="2026-09-03")
    frame = survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()

    masks = challenger_masks(frame)
    selected = masks["X02_limit_adjusted_momentum"]["selected"].fillna(False)

    if "weak_market" not in frame.columns:
        raise RuntimeError("prepared daily frame is missing frozen weak_market state")

    signal_cols = [
        "date", "instrument", "close",
        "raw_mom20_rank", "clean_mom20_rank", "hit_count20",
        "breadth", "breadth5", "money_effect", "weak_market",
    ]
    x = frame.loc[selected, signal_cols].copy()
    x = x.rename(columns={
        "date": "signal_date",
        "close": "signal_close",
        "weak_market": "signal_weak_market",
    })

    nxt = _next_map(frame)
    x["trade_date"] = x["signal_date"].map(nxt)
    x["exit_date"] = x["trade_date"].map(nxt)
    x = x.dropna(subset=["trade_date", "exit_date"]).copy()
    x["trade_date"] = pd.to_datetime(x["trade_date"]).dt.normalize()
    x["exit_date"] = pd.to_datetime(x["exit_date"]).dt.normalize()
    x = x[x["trade_date"] >= SAMPLE_START].copy()
    # User's intended universe: keep ChiNext, exclude STAR/科创板.
    x = x[~x["instrument"].astype(str).str.upper().str.startswith("SH688")].copy()

    # Safe same-day reference fields only: preclose/limit prices/status are known
    # before or at the open of T and do not use T's future high/close.
    ref_cols = ["date", "instrument", "preclose", "upper_limit", "lower_limit"]
    for optional in ("trade_status", "is_st"):
        if optional in frame.columns:
            ref_cols.append(optional)
    ref = frame[ref_cols].rename(columns={"date": "trade_date"}).copy()
    x = x.merge(ref, on=["trade_date", "instrument"], how="left", validate="many_to_one")
    if "trade_status" in x.columns:
        x = x[x["trade_status"].fillna(0).eq(1)]
    if "is_st" in x.columns:
        x = x[x["is_st"].fillna(1).eq(0)]

    x = x.drop_duplicates(["trade_date", "instrument"]).reset_index(drop=True)
    all_dates = [
        d for d in sorted(frame["date"].drop_duplicates())
        if d >= SAMPLE_START and d <= x["trade_date"].max()
    ]
    return x, all_dates


def _minute_extract(candidates: pd.DataFrame) -> pd.DataFrame:
    missing = [str(p) for p in MINUTE_FILES if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing persisted minute files: {missing}")

    keys = candidates[["trade_date", "exit_date", "instrument"]].drop_duplicates().copy()
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.register("cand", keys)

    files_sql = ",".join("'" + str(p.resolve()).replace("'", "''") + "'" for p in MINUTE_FILES)
    q = f"""
    SELECT
        CAST(c.trade_date AS DATE) AS trade_date,
        CAST(c.exit_date AS DATE) AS exit_date,
        c.instrument,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='09:35' THEN m.open END) AS day_open,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='14:30' THEN m.close END) AS px_1430,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='14:45' THEN m.close END) AS entry_1445,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='14:45' THEN m.volume END) AS entry_volume,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='14:45' THEN m.amount END) AS entry_amount,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.exit_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='09:35' THEN m.open END) AS exit_open,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.exit_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='09:35' THEN m.close END) AS exit_0935,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.exit_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='09:40' THEN m.close END) AS exit_0940,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.exit_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='09:45' THEN m.close END) AS exit_0945,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.exit_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='10:00' THEN m.close END) AS exit_1000
    FROM cand c
    JOIN read_parquet([{files_sql}]) m
      ON m.instrument = c.instrument
     AND (
          CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
          OR CAST(m.datetime AS DATE)=CAST(c.exit_date AS DATE)
     )
    GROUP BY 1,2,3
    """
    out = con.execute(q).df()
    con.close()
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    out["exit_date"] = pd.to_datetime(out["exit_date"])
    return out


def _add_intraday_features(candidates: pd.DataFrame, minute: pd.DataFrame) -> pd.DataFrame:
    x = candidates.merge(minute, on=["trade_date", "exit_date", "instrument"], how="left")
    x["intraday_ret"] = x["entry_1445"] / x["day_open"] - 1.0
    x["tail_ret"] = x["entry_1445"] / x["px_1430"] - 1.0
    x["limit_gap"] = x["upper_limit"] / x["entry_1445"] - 1.0
    x["at_limit"] = x["entry_1445"] >= x["upper_limit"] - 0.011
    x["base_executable"] = (
        x["entry_1445"].notna()
        & x["day_open"].notna()
        & x["px_1430"].notna()
        & x["entry_volume"].fillna(0).gt(0)
        & x["entry_amount"].fillna(0).gt(0)
        & x["upper_limit"].notna()
        & ~x["at_limit"].fillna(True)
    )
    return x


def _stamp_duty(date: pd.Timestamp) -> float:
    # Sell-side stamp duty was cut from 0.10% to 0.05% on 2023-08-28.
    return 0.0005 if pd.Timestamp(date) >= pd.Timestamp("2023-08-28") else 0.0010


def _net_return(entry: pd.Series, exit_px: pd.Series, dates: pd.Series, cost_name: str) -> pd.Series:
    spec = COSTS[cost_name]
    stamp = pd.to_datetime(dates).map(_stamp_duty).astype(float)
    buy_cash = entry * (1.0 + spec.slippage_each_side) * (1.0 + spec.commission_each_side)
    sell_cash = (
        exit_px
        * (1.0 - spec.slippage_each_side)
        * (1.0 - spec.commission_each_side - stamp)
    )
    return sell_cash / buy_cash - 1.0


def _exit_column(label: str) -> str:
    return {
        "OPEN": "exit_open",
        "09:35": "exit_0935",
        "09:40": "exit_0940",
        "09:45": "exit_0945",
        "10:00": "exit_1000",
    }[label]


def _eligible(x: pd.DataFrame, market_gate: str, rank_mode: str, limit_buffer: float) -> pd.DataFrame:
    y = x[x["base_executable"] & x["limit_gap"].ge(limit_buffer)].copy()
    if market_gate == "NOT_WEAK":
        y = y[~y["signal_weak_market"].fillna(True)]
    elif market_gate == "BREADTH_POS":
        y = y[y["breadth"].fillna(-1).gt(0)]
    elif market_gate != "ALL":
        raise ValueError(market_gate)

    if rank_mode == "CONFIRM_COMBO":
        y = y[y["intraday_ret"].gt(0) & y["tail_ret"].gt(0)].copy()
    elif rank_mode != "SIGNAL":
        raise ValueError(rank_mode)

    if y.empty:
        return y

    if rank_mode == "SIGNAL":
        y["score"] = y["clean_mom20_rank"].fillna(-np.inf)
    else:
        by_day = y.groupby("trade_date", sort=False)
        y["r_signal"] = by_day["clean_mom20_rank"].rank(pct=True)
        y["r_intraday"] = by_day["intraday_ret"].rank(pct=True)
        y["r_tail"] = by_day["tail_ret"].rank(pct=True)
        y["score"] = (y["r_signal"] + y["r_intraday"] + y["r_tail"]) / 3.0
    return y


def _select_top(y: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if y.empty:
        return y
    z = y.sort_values(
        ["trade_date", "score", "clean_mom20_rank", "instrument"],
        ascending=[True, False, False, True],
    ).copy()
    z["rank"] = z.groupby("trade_date").cumcount() + 1
    counts = z.groupby("trade_date")["instrument"].transform("size")
    return z[(z["rank"] <= top_n) & (counts >= top_n)].copy()


def _portfolio_series(
    selected: pd.DataFrame,
    all_dates: list[pd.Timestamp],
    exit_label: str,
    cost_name: str,
) -> tuple[pd.Series, pd.DataFrame]:
    exit_col = _exit_column(exit_label)
    z = selected[selected[exit_col].notna()].copy()
    if z.empty:
        idx = pd.DatetimeIndex(all_dates)
        return pd.Series(0.0, index=idx), z
    z["net_return"] = _net_return(z["entry_1445"], z[exit_col], z["trade_date"], cost_name)
    daily = z.groupby("trade_date")["net_return"].mean()
    idx = pd.DatetimeIndex(all_dates)
    return daily.reindex(idx, fill_value=0.0), z


def _metrics(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    s = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if s.empty:
        return {"n_days": 0}
    equity = (1.0 + s).cumprod()
    total = float(equity.iloc[-1] - 1.0)
    elapsed_days = max(1, int((s.index[-1] - s.index[0]).days))
    cagr = float(equity.iloc[-1] ** (365.25 / elapsed_days) - 1.0)
    peak = equity.cummax()
    dd = equity / peak - 1.0
    vol = float(s.std(ddof=1))
    sharpe = float(s.mean() / vol * np.sqrt(252)) if vol > 0 else None
    max_dd = float(dd.min())
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else None
    active = s[s.ne(0)]
    yearly = (1.0 + s).groupby(s.index.year).prod() - 1.0
    return {
        "n_days": int(len(s)),
        "active_days": int(len(active)),
        "exposure_fraction": float(len(active) / len(s)),
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "calmar": calmar,
        "mean_active_day": float(active.mean()) if len(active) else None,
        "active_win_rate": float((active > 0).mean()) if len(active) else None,
        "worst_day": float(s.min()),
        "best_day": float(s.max()),
        "yearly_returns": {str(int(k)): float(v) for k, v in yearly.items()},
        "trade_rows": int(len(ledger)),
        "median_names_per_active_day": (
            float(ledger.groupby("trade_date")["instrument"].nunique().median())
            if not ledger.empty else None
        ),
    }


def _slice(
    series: pd.Series,
    ledger: pd.DataFrame,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> tuple[pd.Series, pd.DataFrame]:
    s = series
    z = ledger
    if start is not None:
        s = s[s.index >= start]
        z = z[z["trade_date"] >= start]
    if end is not None:
        s = s[s.index <= end]
        z = z[z["trade_date"] <= end]
    return s, z


def _evaluate_spec(
    features: pd.DataFrame,
    all_dates: list[pd.Timestamp],
    market_gate: str,
    rank_mode: str,
    top_n: int,
    limit_buffer: float,
    exit_label: str,
    cost_name: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    y = _eligible(features, market_gate, rank_mode, limit_buffer)
    selected = _select_top(y, top_n)
    series, ledger = _portfolio_series(selected, all_dates, exit_label, cost_name)

    all_s, all_l = _slice(series, ledger, None, None)
    dev_s, dev_l = _slice(series, ledger, None, OOS_START - pd.Timedelta(days=1))
    oos_s, oos_l = _slice(series, ledger, OOS_START, None)
    return {
        "all": _metrics(all_s, all_l),
        "development_2021_2023": _metrics(dev_s, dev_l),
        "oos_2024_2026": _metrics(oos_s, oos_l),
    }, ledger


def run() -> dict[str, Any]:
    candidates, all_dates = _prepare_candidates()
    minute = _minute_extract(candidates)
    features = _add_intraday_features(candidates, minute)
    if features["base_executable"].any():
        first_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].min())
        last_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].max())
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]

    report: dict[str, Any] = {
        "methodology": {
            "signal": "X02 LIMIT_ADJUSTED_MOMENTUM fixed on T-1 close",
            "selected_rule": "raw_mom20_rank>=0.80 & clean_mom20_rank>=0.80 & hit_count20<=1",
            "entry": "T 14:45 5m bar close; this avoids using the 14:45 bar open when bars are end-labelled",
            "execution_filter": "non-ST/trading, valid 14:45 volume+amount, not at upper limit, configurable limit buffer",
            "market_gate": "NOT_WEAK uses the existing frozen weak_market flag from T-1 only",
            "intraday_confirmation": "for CONFIRM_COMBO, T price at 14:45 > day open and 14:45 > 14:30; all known at entry",
            "ranking": "SIGNAL=clean momentum rank; CONFIRM_COMBO=equal-weight percentile ranks of clean momentum, day return, final-15m return",
            "portfolio": "equal-weight Top-N; require at least N executable names or stay in cash",
            "exit": "next session first-bar open or 5m bar close at requested time",
            "oos_split": "2024-01-01 fixed before this V4.3 test",
            "stamp_duty": "sell 0.10% before 2023-08-28; 0.05% on/after 2023-08-28",
            "primary_spec_preregistered": PRIMARY_SPEC,
        },
        "coverage": {
            "candidate_rows": int(len(candidates)),
            "candidate_dates": int(candidates["trade_date"].nunique()),
            "minute_rows_matched": int(len(minute)),
            "base_executable_rows": int(features["base_executable"].sum()),
            "base_executable_dates": int(features.loc[features["base_executable"], "trade_date"].nunique()),
            "actual_trade_start": str(features.loc[features["base_executable"], "trade_date"].min().date())
                if features["base_executable"].any() else None,
            "actual_trade_end": str(features.loc[features["base_executable"], "trade_date"].max().date())
                if features["base_executable"].any() else None,
        },
        "cost_specs": {k: asdict(v) for k, v in COSTS.items()},
        "primary": {},
        "sensitivity": [],
    }

    primary_metrics, primary_ledger = _evaluate_spec(
        features, all_dates,
        PRIMARY_SPEC["market_gate"], PRIMARY_SPEC["rank_mode"],
        PRIMARY_SPEC["top_n"], PRIMARY_SPEC["limit_buffer"],
        PRIMARY_SPEC["exit"], PRIMARY_SPEC["cost"],
    )
    report["primary"] = {
        "spec": PRIMARY_SPEC,
        "metrics": primary_metrics,
    }

    # Focused sensitivity grid. These are diagnostics, not a post-hoc replacement
    # for the pre-registered primary strategy.
    for market_gate, rank_mode in (
        ("ALL", "SIGNAL"),
        ("NOT_WEAK", "SIGNAL"),
        ("ALL", "CONFIRM_COMBO"),
        ("NOT_WEAK", "CONFIRM_COMBO"),
    ):
        for top_n in (3, 5, 10):
            for limit_buffer in (0.0, 0.005, 0.01):
                for exit_label in EXIT_LABELS:
                    for cost_name in ("BASE", "CONSERVATIVE"):
                        metrics, _ = _evaluate_spec(
                            features, all_dates, market_gate, rank_mode,
                            top_n, limit_buffer, exit_label, cost_name,
                        )
                        report["sensitivity"].append({
                            "market_gate": market_gate,
                            "rank_mode": rank_mode,
                            "top_n": top_n,
                            "limit_buffer": limit_buffer,
                            "exit": exit_label,
                            "cost": cost_name,
                            "metrics": metrics,
                        })

    # Exploratory leaderboard is explicitly OOS-labelled and cannot supersede
    # the primary result without another future holdout.
    leaderboard = sorted(
        report["sensitivity"],
        key=lambda r: (
            r["metrics"]["oos_2024_2026"].get("cagr")
            if r["metrics"]["oos_2024_2026"].get("cagr") is not None else -999
        ),
        reverse=True,
    )[:20]
    report["exploratory_oos_top20"] = leaderboard

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if not primary_ledger.empty:
        cols = [
            "trade_date", "exit_date", "instrument", "rank", "score",
            "clean_mom20_rank", "raw_mom20_rank", "hit_count20",
            "intraday_ret", "tail_ret", "limit_gap",
            "entry_1445", "exit_open", "exit_0935", "exit_0940", "exit_0945", "exit_1000",
        ]
        primary_ledger[cols].sort_values(["trade_date", "rank"]).to_csv(LEDGER, index=False)

    print(json.dumps({
        "coverage": report["coverage"],
        "primary": report["primary"],
        "exploratory_oos_top5": leaderboard[:5],
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
