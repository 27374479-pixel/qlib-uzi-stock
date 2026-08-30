"""Five-minute execution layer for causal event/theme/role daily candidates.

The daily model produces context, never an entry by itself.  On the following
session this module waits for observable selling pressure, a reclaim of VWAP,
and synchronous peer demand.  Execution is always the *next* bar open.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from daily_event_role_backtest import (
    Config as DailyConfig,
    add_roles,
    attach_outcomes,
    build_market_state,
    build_theme_state,
    load_panel,
    make_signals,
)


ROOT = Path(__file__).resolve().parent
MINUTE_DIR = ROOT / "data_lake" / "raw" / "baostock" / "equity_5min"


@dataclass(frozen=True)
class Config:
    universe: str = "csi800"
    start: str = "2024-01-01"
    end: str = "2026-07-17"
    oos_start: str = "2025-07-01"
    round_trip_cost: float = 0.0018
    min_bars: int = 45
    max_positions: int = 3
    probe_weight: float = 1 / 3
    output: str = "output/event_role_minute_execution.json"
    trades_output: str = "output/event_role_minute_execution_trades.parquet"


def _load_minutes(
    instruments: set[str], start: pd.Timestamp, end: pd.Timestamp, min_bars: int
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    columns = ["instrument", "datetime", "open", "high", "low", "close", "volume", "amount"]
    for number, instrument in enumerate(sorted(instruments), 1):
        path = MINUTE_DIR / f"{instrument}.parquet"
        if not path.exists():
            continue
        item = pd.read_parquet(path, columns=columns)
        item["datetime"] = pd.to_datetime(item["datetime"])
        item = item.loc[item["datetime"].between(start, end + pd.Timedelta(days=1))].copy()
        if item.empty:
            continue
        item = item.sort_values("datetime")
        counts = item.groupby(item["datetime"].dt.normalize())["datetime"].transform("size")
        item = item.loc[counts >= min_bars]
        if not item.empty:
            parts.append(item)
        if number % 200 == 0:
            print(f"minute files checked {number}/{len(instruments)}", flush=True)
    if not parts:
        return pd.DataFrame()
    frame = pd.concat(parts, ignore_index=True)
    for column in ("open", "high", "low", "close", "volume", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["date"] = frame["datetime"].dt.normalize()
    return frame.dropna(subset=["open", "high", "low", "close"])


def _prepare_intraday_context(minutes: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    daily = panel[["instrument", "date", "preclose", "industry_code"]].drop_duplicates(
        ["instrument", "date"], keep="last"
    )
    frame = minutes.merge(daily, on=["instrument", "date"], how="inner")
    frame = frame.sort_values(["instrument", "date", "datetime"])
    keys = ["instrument", "date"]
    frame["cum_amount"] = frame.groupby(keys)["amount"].cumsum()
    frame["cum_volume"] = frame.groupby(keys)["volume"].cumsum()
    frame["vwap"] = frame["cum_amount"] / frame["cum_volume"].replace(0, np.nan)
    # BaoStock amount is currency and volume is shares for this cache.  Protect
    # against provider unit variations by falling back when VWAP is implausible.
    implausible = ~frame["vwap"].between(frame["low"] * 0.8, frame["high"] * 1.2)
    frame.loc[implausible, "vwap"] = (
        (frame["high"] + frame["low"] + frame["close"]) / 3
    ).groupby([frame["instrument"], frame["date"]]).expanding().mean().reset_index(level=[0, 1], drop=True)
    frame["intraday_ret"] = frame["close"] / frame["preclose"] - 1
    peer_keys = ["datetime", "industry_code"]
    peer = frame.groupby(peer_keys).agg(
        peer_n=("instrument", "nunique"),
        peer_positive_n=("intraday_ret", lambda x: int((x > 0).sum())),
        peer_median_ret=("intraday_ret", "median"),
    ).reset_index()
    market = frame.groupby("datetime").agg(
        market_median_ret=("intraday_ret", "median"),
    ).reset_index()
    return frame.merge(peer, on=peer_keys, how="left").merge(market, on="datetime", how="left")


def _find_trigger(day: pd.DataFrame, previous_close: float) -> tuple[int | None, dict[str, Any]]:
    day = day.sort_values("datetime").reset_index(drop=True)
    if len(day) < 4:
        return None, {"reject_reason": "too_few_bars"}
    day_open = float(day.iloc[0]["open"])
    gap = day_open / previous_close - 1
    if gap < -0.055 or gap > 0.055:
        return None, {"reject_reason": "opening_gap_outside", "gap": gap}
    cumulative_high = day["high"].cummax()
    cumulative_low = day["low"].cummin()
    prior_high = day["high"].shift(1)
    probe_pos: int | None = None
    probe_details: dict[str, Any] = {}
    for pos in range(2, min(len(day) - 1, 40)):
        row = day.iloc[pos]
        clock = row["datetime"].time()
        if clock < pd.Timestamp("09:45").time() or clock > pd.Timestamp("14:00").time():
            continue
        drawdown = float(cumulative_low.iloc[pos] / cumulative_high.iloc[pos] - 1)
        released_supply = (
            drawdown <= -0.014
            or float(cumulative_low.iloc[pos] / previous_close - 1) <= -0.008
        )
        peer_support = (
            int(row["peer_n"]) >= 3
            and int(row["peer_positive_n"]) >= 2
            and float(row["peer_median_ret"] - row["market_median_ret"]) >= 0.002
        )
        stabilization = (
            float(row["close"]) >= float(row["low"]) * 1.004
            and float(row["close"]) > float(day.iloc[pos - 1]["close"])
        )
        not_chasing = float(row["intraday_ret"]) <= 0.05
        if released_supply and stabilization and peer_support and not_chasing:
            probe_pos = pos
            probe_details = {
                "probe_datetime": row["datetime"],
                "gap": gap,
                "drawdown_before_probe": drawdown,
                "probe_return": float(row["intraday_ret"]),
                "peer_n": int(row["peer_n"]),
                "peer_positive_n": int(row["peer_positive_n"]),
                "peer_excess": float(row["peer_median_ret"] - row["market_median_ret"]),
            }
            break
    if probe_pos is None:
        return None, {"reject_reason": "no_divergence_stabilization"}

    confirm_pos: int | None = None
    for pos in range(probe_pos + 1, min(len(day) - 1, 42)):
        row = day.iloc[pos]
        peer_support = (
            int(row["peer_n"]) >= 3
            and int(row["peer_positive_n"]) >= 2
            and float(row["peer_median_ret"] - row["market_median_ret"]) >= 0.002
        )
        reclaim = (
            float(row["close"]) > float(row["vwap"]) * 1.001
            and float(row["close"]) > float(prior_high.iloc[pos])
            and float(row["close"]) > day_open
            and float(row["intraday_ret"]) <= 0.075
        )
        if reclaim and peer_support:
            confirm_pos = pos
            probe_details.update(
                {
                    "confirm_datetime": row["datetime"],
                    "confirm_return": float(row["intraday_ret"]),
                    "confirmed": True,
                }
            )
            break
    if confirm_pos is None:
        probe_details.update({"confirm_datetime": pd.NaT, "confirm_return": np.nan, "confirmed": False})
    probe_details["confirm_position"] = confirm_pos
    return probe_pos, probe_details


def _execute_candidates(
    candidates: pd.DataFrame,
    context: pd.DataFrame,
    cost: float,
    probe_weight: float,
) -> tuple[pd.DataFrame, dict[str, int]]:
    groups = {
        (instrument, pd.Timestamp(date)): group.sort_values("datetime").reset_index(drop=True)
        for (instrument, date), group in context.groupby(["instrument", "date"], sort=False)
    }
    rows: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for candidate in candidates.to_dict("records"):
        key = (candidate["instrument"], pd.Timestamp(candidate["entry_date"]))
        day = groups.get(key)
        if day is None:
            rejected["minute_day_missing"] = rejected.get("minute_day_missing", 0) + 1
            continue
        probe, details = _find_trigger(day, float(candidate["close"]))
        if probe is None:
            reason = details["reject_reason"]
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        if probe + 1 >= len(day):
            rejected["next_bar_missing"] = rejected.get("next_bar_missing", 0) + 1
            continue
        entry_row = day.iloc[probe + 1]
        probe_price = float(entry_row["open"])
        upper = float(candidate["close"] * (1 + candidate["limit_ratio"]))
        if probe_price >= upper - 0.011 and float(entry_row["low"]) >= upper - 0.011:
            rejected["next_bar_locked_up"] = rejected.get("next_bar_locked_up", 0) + 1
            continue
        result = {
            "instrument": candidate["instrument"],
            "setup_date": candidate["date"],
            "entry_date": candidate["entry_date"],
            "setup": candidate["setup"],
            "daily_rank": candidate["daily_rank"],
            "industry_code": candidate["industry_code"],
            "entry_datetime": entry_row["datetime"],
            "entry_price": probe_price,
            "probe_price": probe_price,
            "probe_weight": probe_weight,
            **details,
        }
        confirm_pos = details.get("confirm_position")
        confirm_price = np.nan
        confirm_weight = 0.0
        if confirm_pos is not None and int(confirm_pos) + 1 < len(day):
            confirm_row = day.iloc[int(confirm_pos) + 1]
            candidate_price = float(confirm_row["open"])
            if not (
                candidate_price >= upper - 0.011
                and float(confirm_row["low"]) >= upper - 0.011
            ):
                confirm_price = candidate_price
                confirm_weight = 1.0 - probe_weight
        result["confirm_price"] = confirm_price
        result["confirm_weight"] = confirm_weight
        result["invested_weight"] = probe_weight + confirm_weight
        # A-share cash equities are T+1.  A position opened today cannot be
        # stopped out today, even when the reclaim fails.  Observe the first
        # bar of the next session and execute at the following bar's open.
        dates = sorted(
            date
            for instrument, date in groups
            if instrument == candidate["instrument"] and date > key[1]
        )
        if not dates:
            rejected["next_session_missing"] = rejected.get("next_session_missing", 0) + 1
            continue
        next_day = groups[(candidate["instrument"], dates[0])]
        if len(next_day) < 2:
            rejected["next_exit_bar_missing"] = rejected.get("next_exit_bar_missing", 0) + 1
            continue
        exit_price = float(next_day.iloc[1]["open"])
        exit_datetime = next_day.iloc[1]["datetime"]
        exit_reason = "t_plus_one_after_first_bar"
        result["exit_datetime"] = exit_datetime
        result["exit_price"] = exit_price
        result["exit_reason"] = exit_reason
        probe_pnl = probe_weight * (exit_price / probe_price - 1 - cost)
        confirm_pnl = (
            confirm_weight * (exit_price / confirm_price - 1 - cost)
            if confirm_weight > 0 and np.isfinite(confirm_price)
            else 0.0
        )
        # Return is on the capital slot reserved for this candidate.  Cash not
        # deployed after a failed confirmation contributes zero, not a scaled-up
        # fictitious trade return.
        result["return"] = float(probe_pnl + confirm_pnl)
        rows.append(result)
    return pd.DataFrame(rows), rejected


def _metrics(trades: pd.DataFrame, config: Config) -> dict[str, Any]:
    if trades.empty:
        return {"n": 0}
    values = trades["return"]
    selected = trades.sort_values(["entry_date", "daily_rank"]).groupby("entry_date").head(config.max_positions)
    daily = selected.groupby("entry_date")["return"].mean().sort_index()
    equity = (1 + daily).cumprod()
    years = max((daily.index.max() - daily.index.min()).days / 365.25, 1 / 252)
    cagr = float(equity.iloc[-1] ** (1 / years) - 1)
    drawdown = equity / equity.cummax() - 1
    vol = float(daily.std(ddof=1) * math.sqrt(252)) if len(daily) > 1 else None
    return {
        "n": int(len(trades)),
        "active_days": int(len(daily)),
        "mean": float(values.mean()),
        "median": float(values.median()),
        "win_rate": float((values > 0).mean()),
        "total_return": float(equity.iloc[-1] - 1),
        "cagr": cagr,
        "max_drawdown": float(drawdown.min()),
        "annualized_volatility": vol,
        "sharpe_zero_rf": float(cagr / vol) if vol and vol > 0 else None,
    }


def run(config: Config) -> dict[str, Any]:
    daily_config = DailyConfig(
        universe=config.universe,
        start=config.start,
        end=config.end,
        oos_start=config.oos_start,
        round_trip_cost=config.round_trip_cost,
    )
    panel, daily_metadata = load_panel(daily_config)
    market = build_market_state(panel)
    theme = build_theme_state(panel)
    signals = make_signals(add_roles(panel, theme, market))
    candidates = attach_outcomes(signals, panel, config.round_trip_cost)
    candidates = candidates.loc[candidates["entry_filled"].fillna(False)].copy()
    available = {path.stem.upper() for path in MINUTE_DIR.glob("*.parquet")}
    peer_instruments = set(panel["instrument"].unique()) & available
    minutes = _load_minutes(
        peer_instruments, pd.Timestamp(config.start), pd.Timestamp(config.end), config.min_bars
    )
    if minutes.empty:
        raise RuntimeError("no complete minute data")
    context = _prepare_intraday_context(minutes, panel)
    trades, rejected = _execute_candidates(
        candidates, context, config.round_trip_cost, config.probe_weight
    )
    split = pd.Timestamp(config.oos_start)
    report = {
        "config": asdict(config),
        "daily_data": daily_metadata,
        "minute_instruments": int(minutes["instrument"].nunique()),
        "candidate_signals": int(len(candidates)),
        "rejected": rejected,
        "all": _metrics(trades, config),
        "development": _metrics(trades.loc[trades["entry_date"] < split], config),
        "oos": _metrics(trades.loc[trades["entry_date"] >= split], config),
        "by_setup_oos": {
            setup: _metrics(group, config)
            for setup, group in trades.loc[trades["entry_date"] >= split].groupby("setup")
        },
        "limitations": [
            "Minute coverage is incomplete and changing while BaoStock backfill runs.",
            "CSRC industry remains a theme proxy; real Eastmoney concepts/reasons are used only in recent replay.",
            "Thresholds are fixed before reviewing this minute OOS result.",
        ],
    }
    output, trades_output = ROOT / config.output, ROOT / config.trades_output
    output.parent.mkdir(parents=True, exist_ok=True)
    trades_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    trades.to_parquet(trades_output, index=False)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return report


def parse_args() -> Config:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default=Config.universe)
    parser.add_argument("--start", default=Config.start)
    parser.add_argument("--end", default=Config.end)
    parser.add_argument("--oos-start", default=Config.oos_start)
    parser.add_argument("--round-trip-cost", type=float, default=Config.round_trip_cost)
    parser.add_argument("--max-positions", type=int, default=Config.max_positions)
    parser.add_argument("--probe-weight", type=float, default=Config.probe_weight)
    parser.add_argument("--output", default=Config.output)
    parser.add_argument("--trades-output", default=Config.trades_output)
    return Config(**vars(parser.parse_args()))


if __name__ == "__main__":
    run(parse_args())
