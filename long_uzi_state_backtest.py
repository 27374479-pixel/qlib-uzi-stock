"""Leakage-safe long-sample replay of a public short-term trading synthesis.

This file is deliberately a separate research model.  It is not presented as
the private method of any one trader.  It converts recurring, observable ideas
from the two ``48位游资悟道心得语录`` volumes into a small state machine:

    market permission -> main-line/cohort confirmation -> leader/price action
    confirmation -> next-bar executable entry -> rule-based risk exit.

The implementation is designed for the long BaoStock 5-minute backfill.  It
processes one instrument at a time, materialises compact point-in-time feature
files, and only then scores the cross-sectional snapshots.  This keeps the
memory footprint bounded and makes it possible to audit every signal.

Important limitations:

* ``industry_code`` is a point-in-time cohort proxy, not a news interpreter.
* The default universe is a fixed CSI800 membership snapshot at the start
  date; it is not a survivorship-free all-market universe.
* All thresholds are pre-declared heuristics.  They must be evaluated out of
  sample and are not tuned to the test-period winners.
* Board queue/order-book information is unavailable.  A locked next bar is
  marked unfilled rather than silently treated as a successful buy.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from config import OUTPUT_DIR, PROJECT_ROOT


BAOSTOCK_MINUTE_DIR = PROJECT_ROOT / "data_lake" / "raw" / "baostock" / "equity_5min"
EASTMONEY_MINUTE_DIR = PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "equity_5min"
INDUSTRY_DIR = PROJECT_ROOT / "data_lake" / "raw" / "baostock" / "industry_snapshots"
CACHE_ROOT = PROJECT_ROOT / "data_lake" / "derived" / "long_uzi_state"
CACHE_MANIFEST = CACHE_ROOT / "manifest.json"

DEFAULT_SIGNAL_TIMES = "09:45,10:15,10:45,13:30,14:00,14:30"
MODEL_NAME = "book_fusion_state_machine_v1"
CACHE_SCHEMA_VERSION = "20260825_limit_state_semantics_v5"


@dataclass(frozen=True)
class Config:
    start: str = "20240102"
    end: str = "20260824"
    universe: str = "csi800_start"
    universe_asof: str = "20240102"
    signal_times: str = DEFAULT_SIGNAL_TIMES
    top_n: int = 5
    min_daily_bars: int = 40
    min_history_days: int = 40
    max_instruments: int = 0
    refresh_cache: bool = False
    open_cost: float = 0.0003
    close_cost: float = 0.0013
    profile: str = "base"
    output: str = str(OUTPUT_DIR / "long_uzi_state_latest.json")


@dataclass(frozen=True)
class RuleProfile:
    """A pre-declared interpretation of the same book-derived principles."""

    name: str
    group_n: int
    group_breadth: float
    group_return: float
    group_relative: float
    group_amount: float
    prior_ret10: float
    prior_limit_up5: float
    no_chase_return: float
    amount_low: float
    amount_high: float
    trend_return_low: float
    trend_return_high: float
    trend_from_open: float
    trend_late_momentum: float
    trend_leader: float
    pullback_from_high_low: float
    pullback_from_high_high: float
    pullback_recovery: float
    pullback_late_momentum: float
    pullback_leader: float
    reseal_gap_low: float
    reseal_gap_high: float
    reseal_late_momentum: float
    reseal_leader: float
    rebound_from_high_low: float
    rebound_from_high_high: float
    rebound_recovery: float
    rebound_late_momentum: float
    rebound_leader: float
    market_policy: str = "all_permitted"


PROFILE_LIBRARY: dict[str, RuleProfile] = {
    "base": RuleProfile(
        name="base",
        group_n=4,
        group_breadth=0.20,
        group_return=0.002,
        group_relative=0.002,
        group_amount=0.65,
        prior_ret10=0.03,
        prior_limit_up5=1,
        no_chase_return=0.075,
        amount_low=0.55,
        amount_high=3.80,
        trend_return_low=0.006,
        trend_return_high=0.070,
        trend_from_open=0.001,
        trend_late_momentum=-0.001,
        trend_leader=0.68,
        pullback_from_high_low=-0.075,
        pullback_from_high_high=-0.008,
        pullback_recovery=0.010,
        pullback_late_momentum=0.001,
        pullback_leader=0.65,
        reseal_gap_low=-0.035,
        reseal_gap_high=-0.001,
        reseal_late_momentum=0.001,
        reseal_leader=0.70,
        rebound_from_high_low=-0.100,
        rebound_from_high_high=-0.015,
        rebound_recovery=0.015,
        rebound_late_momentum=0.002,
        rebound_leader=0.62,
    ),
    "strict_core": RuleProfile(
        name="strict_core",
        group_n=5,
        group_breadth=0.30,
        group_return=0.004,
        group_relative=0.003,
        group_amount=0.85,
        prior_ret10=0.04,
        prior_limit_up5=1,
        no_chase_return=0.055,
        amount_low=0.75,
        amount_high=2.80,
        trend_return_low=0.008,
        trend_return_high=0.055,
        trend_from_open=0.002,
        trend_late_momentum=0.0,
        trend_leader=0.74,
        pullback_from_high_low=-0.060,
        pullback_from_high_high=-0.012,
        pullback_recovery=0.015,
        pullback_late_momentum=0.002,
        pullback_leader=0.72,
        reseal_gap_low=-0.025,
        reseal_gap_high=-0.003,
        reseal_late_momentum=0.002,
        reseal_leader=0.75,
        rebound_from_high_low=-0.080,
        rebound_from_high_high=-0.020,
        rebound_recovery=0.020,
        rebound_late_momentum=0.003,
        rebound_leader=0.68,
    ),
    "balanced_confirmation": RuleProfile(
        name="balanced_confirmation",
        group_n=3,
        group_breadth=0.15,
        group_return=0.001,
        group_relative=0.001,
        group_amount=0.55,
        prior_ret10=0.02,
        prior_limit_up5=1,
        no_chase_return=0.085,
        amount_low=0.45,
        amount_high=5.00,
        trend_return_low=0.004,
        trend_return_high=0.080,
        trend_from_open=0.0,
        trend_late_momentum=-0.002,
        trend_leader=0.63,
        pullback_from_high_low=-0.100,
        pullback_from_high_high=-0.005,
        pullback_recovery=0.008,
        pullback_late_momentum=0.0005,
        pullback_leader=0.60,
        reseal_gap_low=-0.050,
        reseal_gap_high=-0.0005,
        reseal_late_momentum=0.0005,
        reseal_leader=0.65,
        rebound_from_high_low=-0.120,
        rebound_from_high_high=-0.010,
        rebound_recovery=0.010,
        rebound_late_momentum=0.001,
        rebound_leader=0.58,
    ),
}

# A separate, deliberately low-exposure interpretation of the book's
# “退潮/冰点少做，先等情绪出现方向” rule.  It is declared before the full
# evaluation and is not selected from the test-period winners.
PROFILE_LIBRARY["defensive_rebound"] = replace(
    PROFILE_LIBRARY["base"],
    name="defensive_rebound",
    market_policy="weak_or_ice_rebound",
)


def _resolve_profile(profile: str | RuleProfile | None) -> RuleProfile:
    if isinstance(profile, RuleProfile):
        return profile
    name = str(profile or "base")
    if name not in PROFILE_LIBRARY:
        raise ValueError(f"unknown rule profile: {name}; choose from {sorted(PROFILE_LIBRARY)}")
    return PROFILE_LIBRARY[name]


def _date(value: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"invalid date: {value}")
    return parsed.normalize()


def _instrument_code(instrument: str) -> str:
    return str(instrument).upper().replace("SH", "").replace("SZ", "").replace("BJ", "")


def _limit_ratio(instrument: str) -> float:
    code = _instrument_code(instrument)
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    if code.startswith(("4", "8", "920")):
        return 0.30
    return 0.10


def _round_tick(value: float | pd.Series) -> float | pd.Series:
    return np.round(np.asarray(value, dtype=float) / 0.01) * 0.01


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    if isinstance(value, tuple):
        return [_safe_json(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return [_safe_json(v) for v in value.tolist()]
    return value


def _minute_paths() -> dict[str, list[Path]]:
    paths: dict[str, list[Path]] = {}
    for root in (BAOSTOCK_MINUTE_DIR, EASTMONEY_MINUTE_DIR):
        for path in sorted(root.glob("*.parquet")):
            paths.setdefault(path.stem.upper(), []).append(path)
    return paths


def _fixed_universe(universe: str, asof: str) -> set[str]:
    """Resolve a point-in-time stock pool before reading any price files."""

    market_name = universe.removesuffix("_start")
    if market_name not in {"csi300", "csi500", "csi800"}:
        raise ValueError(f"unsupported fixed universe: {universe}")
    import qlib
    from qlib.constant import REG_CN
    from qlib.data import D

    from config import QLIB_DATA_DIR

    qlib.init(provider_uri=str(QLIB_DATA_DIR), region=REG_CN)
    cutoff = _date(asof)
    mapping = D.list_instruments(instruments=D.instruments(market=market_name), as_list=False)
    result: set[str] = set()
    for instrument, intervals in mapping.items():
        if not any(start.normalize() <= cutoff <= end.normalize() for start, end in intervals):
            continue
        raw = str(instrument).upper().replace(".", "")
        if raw.startswith(("SH", "SZ")):
            result.add(raw)
        else:
            code = _instrument_code(raw)
            if code.startswith("6"):
                result.add("SH" + code)
            elif code.startswith(("0", "2", "3")):
                result.add("SZ" + code)
    if not result:
        raise ValueError(f"no instruments found for {universe} as of {asof}")
    return result


def _read_instrument(paths: Iterable[Path], instrument: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Read one instrument and prefer Eastmoney rows on duplicate timestamps."""

    columns = ["instrument", "datetime", "open", "high", "low", "close", "volume", "amount"]
    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if frame.empty:
            continue
        keep = [column for column in columns if column in frame.columns]
        frame = frame[keep].copy()
        frame["instrument"] = instrument
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
        frame = frame.loc[frame["datetime"].between(start - pd.Timedelta(days=75), end + pd.Timedelta(days=6))]
        if frame.empty:
            continue
        for column in columns[2:]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["_priority"] = 3 if "eastmoney" in str(path).lower() else 2
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=columns)
    result = pd.concat(frames, ignore_index=True, sort=False)
    result = (
        result.dropna(subset=["datetime", "open", "high", "low", "close"])
        .sort_values(["instrument", "datetime", "_priority"])
        .drop_duplicates(["instrument", "datetime"], keep="last")
        .drop(columns=["_priority"], errors="ignore")
        .sort_values("datetime")
        .reset_index(drop=True)
    )
    return result


def _daily_features(minutes: pd.DataFrame, min_daily_bars: int) -> pd.DataFrame:
    if minutes.empty:
        return pd.DataFrame()
    frame = minutes.copy()
    frame["date"] = frame["datetime"].dt.normalize()
    daily = (
        frame.groupby("date", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            amount=("amount", "sum"),
            bar_count=("datetime", "size"),
        )
        .reset_index()
    )
    daily = daily.loc[daily["bar_count"] >= min_daily_bars].copy()
    if daily.empty:
        return daily
    ratio = _limit_ratio(str(minutes["instrument"].iloc[0]))
    daily["limit_ratio"] = ratio
    daily["prev_close"] = daily["close"].shift(1)
    daily["upper_limit"] = _round_tick(daily["prev_close"] * (1.0 + ratio))
    daily["lower_limit"] = _round_tick(daily["prev_close"] * (1.0 - ratio))
    daily["ret1"] = daily["close"] / daily["prev_close"] - 1.0
    daily["limit_touched"] = daily["high"] >= daily["upper_limit"] - 0.011
    # A normal limit-up can trade below the limit intraday and still finish
    # sealed.  The old definition accidentally counted only one-word boards,
    # which understated board quality and misclassified most broken boards.
    daily["limit_locked"] = daily["close"] >= daily["upper_limit"] - 0.011
    daily["limit_one_word"] = (
        daily["limit_locked"]
        & (daily["low"] >= daily["upper_limit"] - 0.011)
    )
    daily["limit_broken"] = daily["limit_touched"] & ~daily["limit_locked"]
    daily["limit_down_close"] = daily["close"] <= daily["lower_limit"] + 0.011
    daily["limit_down_locked"] = (
        (daily["open"] <= daily["lower_limit"] + 0.011)
        & (daily["high"] <= daily["lower_limit"] + 0.011)
        & (daily["low"] <= daily["lower_limit"] + 0.011)
    )
    # Equality against True naturally maps the first shifted NaN to False
    # without pandas' object-dtype downcast warning.
    daily["prev_limit_touched"] = daily["limit_touched"].shift(1).eq(True)
    daily["money_effect_component"] = daily["ret1"].where(daily["prev_limit_touched"])
    for window in (3, 5, 10, 20):
        daily[f"ret{window}"] = daily["close"] / daily["close"].shift(window) - 1.0
        daily[f"amount_prev{window}"] = daily["amount"].shift(1).rolling(
            window, min_periods=max(3, window // 2)
        ).mean()
    daily["vol10"] = daily["ret1"].rolling(10, min_periods=7).std()
    daily["prior_limit_up5"] = daily["limit_touched"].shift(1).rolling(5, min_periods=2).sum()
    daily["prior_locked_up5"] = daily["limit_locked"].shift(1).rolling(5, min_periods=2).sum()
    daily["instrument"] = str(minutes["instrument"].iloc[0])
    return daily


def _market_daily(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()
    frame = daily.copy()
    frame["valid_ret"] = frame["ret1"].replace([np.inf, -np.inf], np.nan)
    grouped = frame.groupby("date", sort=True)
    result = grouped.agg(
        universe_n=("instrument", "nunique"),
        ret_median=("valid_ret", "median"),
        up_ratio=("valid_ret", lambda s: float((s > 0).mean())),
        down_ratio=("valid_ret", lambda s: float((s < 0).mean())),
        limit_touched_count=("limit_touched", "sum"),
        limit_locked_count=("limit_locked", "sum"),
        limit_down_count=("limit_down_close", "sum"),
        money_effect=("money_effect_component", "mean"),
    ).reset_index()
    result["breadth"] = result["up_ratio"] - result["down_ratio"]
    result["broken_ratio"] = (
        (result["limit_touched_count"] - result["limit_locked_count"])
        / result["limit_touched_count"].clip(lower=1)
    )
    result["board_quality"] = result["limit_locked_count"] / result["limit_touched_count"].clip(lower=1)
    result["money_effect"] = result["money_effect"].fillna(0.0)
    result["breadth_5d"] = result["breadth"].rolling(5, min_periods=3).mean()
    result["breadth_10d"] = result["breadth"].rolling(10, min_periods=5).mean()
    result["money_effect_5d"] = result["money_effect"].rolling(5, min_periods=3).mean()
    return result.set_index("date").sort_index()


def _load_industry() -> dict[str, tuple[np.ndarray, np.ndarray]]:
    rows: list[pd.DataFrame] = []
    for path in sorted(INDUSTRY_DIR.glob("*.parquet")):
        try:
            frame = pd.read_parquet(path, columns=["snapshot_date", "instrument", "industry_code"])
        except Exception:
            continue
        if not frame.empty:
            rows.append(frame)
    if not rows:
        return {}
    all_rows = pd.concat(rows, ignore_index=True)
    all_rows["snapshot_date"] = pd.to_datetime(all_rows["snapshot_date"], errors="coerce").dt.normalize()
    all_rows["instrument"] = all_rows["instrument"].astype(str).str.upper()
    all_rows["industry_code"] = all_rows["industry_code"].fillna("UNKNOWN").astype(str)
    all_rows = all_rows.dropna(subset=["snapshot_date"]).drop_duplicates(
        ["instrument", "snapshot_date"], keep="last"
    )
    result: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for instrument, group in all_rows.groupby("instrument", sort=False):
        group = group.sort_values("snapshot_date")
        result[instrument] = (
            group["snapshot_date"].to_numpy(dtype="datetime64[ns]"),
            group["industry_code"].to_numpy(dtype=str),
        )
    return result


def _industry_at(mapping: dict[str, tuple[np.ndarray, np.ndarray]], instrument: str, date: pd.Timestamp) -> str:
    item = mapping.get(instrument)
    if item is None:
        return "UNKNOWN"
    dates, codes = item
    position = int(np.searchsorted(dates, np.datetime64(date), side="right") - 1)
    if position < 0:
        return "UNKNOWN"
    return str(codes[position]) or "UNKNOWN"


def _first_bar(day: pd.DataFrame) -> pd.Series | None:
    return day.iloc[0] if not day.empty else None


def _lock_flags(bar: pd.Series, previous_close: float, ratio: float) -> tuple[bool, bool]:
    upper = float(_round_tick(previous_close * (1.0 + ratio)))
    lower = float(_round_tick(previous_close * (1.0 - ratio)))
    locked_up = bool(
        bar["open"] >= upper - 0.011 and bar["low"] >= upper - 0.011 and bar["high"] >= upper - 0.011
    )
    locked_down = bool(bar["open"] <= lower + 0.011 and bar["high"] <= lower + 0.011)
    return locked_up, locked_down


def _exit_price_after_first_bar(day: pd.DataFrame, previous_close: float, ratio: float) -> tuple[float | None, str]:
    """Return the next-bar open after a causal weakness observation.

    The strategy can only know that a bar is weak after that bar has closed.
    Returning that same bar's open or close would therefore mix observation and
    execution.  If the observed bar is limit-down locked, scan forward bar by
    bar and return the first later open after an executable observation.
    """

    if len(day) < 2:
        return None, "no_exit_bar"
    for position in range(len(day) - 1):
        bar = day.iloc[position]
        _, locked_down = _lock_flags(bar, previous_close, ratio)
        opening = float(day.iloc[position + 1]["open"])
        if not locked_down and np.isfinite(opening) and opening > 0:
            return opening, "next_bar_open_after_observation"
    return None, "exit_locked_down"


def _outcomes(
    day_groups: dict[pd.Timestamp, pd.DataFrame],
    date: pd.Timestamp,
    cutoff_position: int,
    previous_close: float,
    ratio: float,
    trading_dates: list[pd.Timestamp],
    date_positions: dict[pd.Timestamp, int],
    open_cost: float,
    close_cost: float,
) -> dict[str, Any]:
    """Build fixed-horizon and rule-based outcomes from bars after the signal."""

    current_day = day_groups.get(date, pd.DataFrame())
    after = current_day.iloc[cutoff_position:]
    if after.empty:
        return {"entry_filled": False, "entry_reason": "no_next_bar"}
    entry_bar = after.iloc[0]
    locked_up, locked_down = _lock_flags(entry_bar, previous_close, ratio)
    entry_open = float(entry_bar["open"])
    base: dict[str, Any] = {
        "entry_datetime": entry_bar["datetime"],
        "entry_open": entry_open,
        "entry_filled": not (locked_up or locked_down),
        "entry_reason": "next_bar_open" if not (locked_up or locked_down) else "next_bar_locked_up" if locked_up else "next_bar_locked_down",
    }
    if not np.isfinite(entry_open) or entry_open <= 0:
        base["entry_filled"] = False
        base["entry_reason"] = "invalid_entry_price"
        return base
    position = date_positions.get(date)
    if position is None:
        base["entry_filled"] = False
        base["entry_reason"] = "signal_date_not_in_calendar"
        return base
    if not base["entry_filled"]:
        return base
    entry = entry_open
    # The first later session's limit prices are based on the signal day's
    # completed close, not on the close from the day before the signal.
    signal_day_close = float(current_day["close"].iloc[-1])
    horizon_rows: dict[int, tuple[pd.Timestamp, pd.DataFrame]] = {}
    for horizon in (1, 2, 5):
        if position + horizon >= len(trading_dates):
            base[f"exit_{horizon}d_filled"] = False
            base[f"exit_{horizon}d_reason"] = "forward_window_missing"
            continue
        exit_date = trading_dates[position + horizon]
        day = day_groups.get(exit_date, pd.DataFrame())
        bar = _first_bar(day)
        if bar is None:
            base[f"exit_{horizon}d_filled"] = False
            base[f"exit_{horizon}d_reason"] = "no_exit_bar"
            continue
        prior_day = day_groups.get(trading_dates[position + horizon - 1], pd.DataFrame())
        prior_day_close = (
            float(prior_day["close"].iloc[-1])
            if not prior_day.empty
            else signal_day_close
        )
        _, down = _lock_flags(bar, prior_day_close, ratio)
        base[f"exit_{horizon}d_filled"] = not down
        base[f"exit_{horizon}d_reason"] = "first_bar_open" if not down else "exit_locked_down"
        base[f"exit_{horizon}d_date"] = exit_date
        base[f"exit_{horizon}d_open"] = float(bar["open"])
        horizon_rows[horizon] = (exit_date, day)
        if not down:
            base[f"return_{horizon}d"] = float(
                float(bar["open"]) / entry - 1.0 - open_cost - close_cost
            )

    # Dynamic rule: sell quickly on a weak first observation; only a clearly
    # positive first observation is allowed to carry to the next session.  This
    # is a pre-declared translation of “弱就走、强则持有/滚动”, not a search
    # over the future best exit.
    d1 = day_groups.get(trading_dates[position + 1], pd.DataFrame()) if position + 1 < len(trading_dates) else pd.DataFrame()
    d1_bar = _first_bar(d1)
    if d1_bar is None:
        base["dynamic_filled"] = False
        base["dynamic_exit_reason"] = "no_dynamic_bar"
        return base
    # Only the first bar's close is observable before making a causal exit
    # decision.  Using the whole next-session close and then selling at that
    # session's open would leak future information.
    d1_first_close = float(d1_bar["close"])
    weak_first = d1_first_close < entry * 0.995 or d1_first_close < float(d1_bar["open"])
    strong_first = d1_first_close >= entry * 1.008 and d1_first_close >= float(d1_bar["open"])
    if weak_first or not strong_first:
        exit_price, exit_reason = _exit_price_after_first_bar(d1, signal_day_close, ratio)
        if exit_price is not None:
            base["dynamic_filled"] = True
            base["dynamic_exit_date"] = trading_dates[position + 1]
            base["dynamic_exit_price"] = exit_price
            base["dynamic_exit_reason"] = "weak_first_bar" if weak_first else "no_follow_through"
            base["dynamic_return"] = float(exit_price / entry - 1.0 - open_cost - close_cost)
        else:
            base["dynamic_filled"] = False
            base["dynamic_exit_reason"] = exit_reason
        return base
    # Strong first bar: hold one more session.  The second day's first bar is
    # also evaluated only after its close, so both weak and strong outcomes
    # exit causally at the next bar's open.  The cap avoids silently
    # turning a short-term model into a buy-and-hold model.
    if position + 2 >= len(trading_dates):
        base["dynamic_filled"] = False
        base["dynamic_exit_reason"] = "forward_window_missing"
        return base
    d2_date = trading_dates[position + 2]
    d2 = day_groups.get(d2_date, pd.DataFrame())
    d2_bar = _first_bar(d2)
    if d2_bar is None:
        base["dynamic_filled"] = False
        base["dynamic_exit_reason"] = "no_dynamic_bar"
        return base
    d2_first_close = float(d2_bar["close"])
    d2_weak = d2_first_close < float(d2_bar["open"]) or d2_first_close < d1_first_close
    if d2_weak:
        exit_price, exit_reason = _exit_price_after_first_bar(d2, float(d1_bar["close"]), ratio)
        if exit_price is None:
            base["dynamic_filled"] = False
            base["dynamic_exit_reason"] = exit_reason
            return base
        base["dynamic_exit_price"] = exit_price
        base["dynamic_exit_reason"] = "second_day_weak"
    else:
        exit_price, exit_reason = _exit_price_after_first_bar(d2, float(d1_bar["close"]), ratio)
        if exit_price is None:
            base["dynamic_filled"] = False
            base["dynamic_exit_reason"] = exit_reason
            return base
        base["dynamic_exit_price"] = exit_price
        base["dynamic_exit_reason"] = "strong_first_then_second_open"
    base["dynamic_filled"] = True
    base["dynamic_exit_date"] = d2_date
    base["dynamic_return"] = float(base["dynamic_exit_price"] / entry - 1.0 - open_cost - close_cost)
    return base


def _asof_rows_for_instrument(
    minutes: pd.DataFrame,
    daily: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    signal_times: list[str],
    trading_dates: list[pd.Timestamp],
    industry_mapping: dict[str, tuple[np.ndarray, np.ndarray]],
    config: Config,
) -> pd.DataFrame:
    if minutes.empty or daily.empty:
        return pd.DataFrame()
    instrument = str(minutes["instrument"].iloc[0])
    ratio = _limit_ratio(instrument)
    daily_by_date = {pd.Timestamp(row["date"]): row for _, row in daily.iterrows()}
    day_groups = {
        pd.Timestamp(day): group.sort_values("datetime").reset_index(drop=True)
        for day, group in minutes.groupby(minutes["datetime"].dt.normalize(), sort=False)
    }
    date_positions = {pd.Timestamp(day): number for number, day in enumerate(trading_dates)}
    daily_dates = sorted(daily_by_date)
    rows: list[dict[str, Any]] = []
    for date in signal_dates:
        current_day = day_groups.get(date)
        if current_day is None or current_day.empty:
            continue
        prior_candidates = [key for key in daily_dates if key < date]
        if len(prior_candidates) < config.min_history_days:
            continue
        prior_date = max(prior_candidates)
        prior = daily_by_date[prior_date]
        previous_close = float(prior["close"])
        previous_amount = float(prior.get("amount_prev5", np.nan))
        industry_code = _industry_at(industry_mapping, instrument, date)
        timestamps = current_day["datetime"].to_numpy(dtype="datetime64[ns]")
        opens = current_day["open"].to_numpy(dtype=float)
        highs = current_day["high"].to_numpy(dtype=float)
        lows = current_day["low"].to_numpy(dtype=float)
        closes = current_day["close"].to_numpy(dtype=float)
        amounts = current_day["amount"].to_numpy(dtype=float)
        cumulative_amount = np.cumsum(np.nan_to_num(amounts, nan=0.0))
        cumulative_high = np.maximum.accumulate(highs)
        cumulative_low = np.minimum.accumulate(lows)
        upper = float(_round_tick(previous_close * (1.0 + ratio)))
        lower = float(_round_tick(previous_close * (1.0 - ratio)))
        for cutoff in signal_times:
            timestamp = pd.Timestamp(f"{date:%Y-%m-%d} {cutoff}:00")
            position = int(np.searchsorted(timestamps, np.datetime64(timestamp), side="right"))
            if position <= 0:
                continue
            last = position - 1
            close_30_position = int(
                np.searchsorted(timestamps, np.datetime64(timestamp - pd.Timedelta(minutes=30)), side="right") - 1
            )
            close_30 = float(closes[close_30_position]) if close_30_position >= 0 else float(opens[0])
            current_close = float(closes[last])
            current_high = float(cumulative_high[last])
            current_low = float(cumulative_low[last])
            bars = int(position)
            cum_amount = float(cumulative_amount[last])
            amount_ratio = (
                cum_amount / (previous_amount * (bars / 48.0))
                if np.isfinite(previous_amount) and previous_amount > 0
                else np.nan
            )
            touched = current_high >= upper - 0.011
            locked = current_close >= upper - 0.011
            one_word = locked and current_low >= upper - 0.011
            broken = touched and not locked
            outcomes = _outcomes(
                day_groups,
                date,
                position,
                previous_close,
                ratio,
                trading_dates,
                date_positions,
                config.open_cost,
                config.close_cost,
            )
            item: dict[str, Any] = {
                "instrument": instrument,
                "signal_date": date,
                "cutoff": cutoff,
                "signal_datetime": timestamp,
                "industry_code": industry_code,
                "prior_date": prior_date,
                "previous_close": previous_close,
                "limit_ratio": ratio,
                "upper_limit": upper,
                "lower_limit": lower,
                "prior_ret1": float(prior.get("ret1", np.nan)),
                "prior_ret3": float(prior.get("ret3", np.nan)),
                "prior_ret5": float(prior.get("ret5", np.nan)),
                "prior_ret10": float(prior.get("ret10", np.nan)),
                "prior_ret20": float(prior.get("ret20", np.nan)),
                "prior_vol10": float(prior.get("vol10", np.nan)),
                "prior_limit_up5": float(prior.get("prior_limit_up5", np.nan)),
                "prior_locked_up5": float(prior.get("prior_locked_up5", np.nan)),
                "prior_amount_prev5": previous_amount,
                "day_open": float(opens[0]),
                "current_close": current_close,
                "current_high": current_high,
                "current_low": current_low,
                "last_bar_close": current_close,
                "last_bar_high": float(highs[last]),
                "last_bar_low": float(lows[last]),
                "bars_asof": bars,
                "cum_amount": cum_amount,
                "amount_ratio_asof": amount_ratio,
                "intraday_return": current_close / previous_close - 1.0 if np.isfinite(previous_close) and previous_close > 0 else np.nan,
                "from_open": current_close / float(opens[0]) - 1.0 if np.isfinite(opens[0]) and opens[0] > 0 else np.nan,
                "from_high": current_close / current_high - 1.0 if current_high > 0 else np.nan,
                "recovery_from_low": current_close / current_low - 1.0 if current_low > 0 else np.nan,
                "late_momentum_30m": current_close / close_30 - 1.0 if close_30 > 0 else np.nan,
                "gap_to_upper": current_close / upper - 1.0 if upper > 0 else np.nan,
                "touched_upper": touched,
                "locked_upper": locked,
                "one_word_upper": one_word,
                "broken_upper": broken,
            }
            item.update(outcomes)
            rows.append(item)
    return pd.DataFrame(rows)


def _cache_paths(config: Config | None = None) -> tuple[Path, Path, Path]:
    root = CACHE_ROOT / (config.universe if config is not None else "default")
    return root / "daily_panel.parquet", root / "market_daily.parquet", root / "asof_panel.parquet"


def _cache_instruments(paths_by_instrument: dict[str, list[Path]], max_instruments: int) -> list[str]:
    instruments = sorted(paths_by_instrument)
    return instruments[:max_instruments] if max_instruments else instruments


def _cache_config(config: Config, instruments: list[str]) -> dict[str, Any]:
    return {
        "cache_schema": CACHE_SCHEMA_VERSION,
        "start": config.start,
        "end": config.end,
        "universe": config.universe,
        "universe_asof": config.universe_asof,
        "signal_times": config.signal_times,
        "min_daily_bars": config.min_daily_bars,
        "min_history_days": config.min_history_days,
        "max_instruments": config.max_instruments,
        "instruments": instruments,
    }


def build_cache(config: Config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    daily_path, market_path, asof_path = _cache_paths(config)
    cache_root = daily_path.parent
    cache_manifest = cache_root / "manifest.json"
    start = _date(config.start)
    end = _date(config.end)
    paths_by_instrument = _minute_paths()
    allowed = _fixed_universe(config.universe, config.universe_asof)
    paths_by_instrument = {
        instrument: paths
        for instrument, paths in paths_by_instrument.items()
        if instrument in allowed
    }
    instruments = _cache_instruments(paths_by_instrument, config.max_instruments)
    if not instruments:
        raise FileNotFoundError("No cached minute files found")
    expected_cache_config = _cache_config(config, instruments)
    if not config.refresh_cache and daily_path.exists() and market_path.exists() and asof_path.exists() and cache_manifest.exists():
        try:
            manifest = json.loads(cache_manifest.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        if manifest.get("config") == expected_cache_config:
            daily = pd.read_parquet(daily_path)
            market = pd.read_parquet(market_path).set_index("date")
            asof = pd.read_parquet(asof_path)
            return daily, market, asof, {
                "cache_reused": True,
                "asof_files": int(asof["instrument"].nunique()),
                "cache_manifest": str(cache_manifest),
            }
        print("  cache exists but configuration/universe changed; rebuilding", flush=True)
    print(f"  long-state instruments={len(instruments)}", flush=True)

    daily_parts: list[pd.DataFrame] = []
    for number, instrument in enumerate(instruments, 1):
        minutes = _read_instrument(paths_by_instrument[instrument], instrument, start, end)
        daily = _daily_features(minutes, config.min_daily_bars)
        if not daily.empty:
            daily = daily.loc[daily["date"].between(start - pd.Timedelta(days=75), end + pd.Timedelta(days=6))].copy()
            daily_parts.append(daily)
        if number == 1 or number % 50 == 0 or number == len(instruments):
            print(f"  daily pass {number}/{len(instruments)}", flush=True)
    if not daily_parts:
        raise ValueError("No completed daily rows from minute files")
    daily_panel = pd.concat(daily_parts, ignore_index=True, sort=False)
    market = _market_daily(daily_panel)
    market_dates = list(market.index)
    if len(market_dates) <= config.min_history_days + 5:
        raise ValueError(f"Too few market dates: {len(market_dates)}")
    # Do not use the maximum observed coverage over the whole sample to
    # decide which earlier dates are usable: that would let a future data
    # availability fact define the historical sample.  The requested fixed
    # universe is known before the replay starts, so use its size instead.
    expected_universe_n = len(allowed) if config.max_instruments == 0 else len(instruments)
    minimum_coverage = max(10, int(expected_universe_n * 0.55))
    max_universe_n = int(market["universe_n"].max())
    usable_market_dates = [
        day
        for day in market_dates
        if market.loc[day, "universe_n"] >= minimum_coverage
    ]
    usable_market_dates = [
        day for day in usable_market_dates if market_dates.index(day) + 5 < len(market_dates)
    ]
    if len(usable_market_dates) <= config.min_history_days:
        raise ValueError("Too few usable dates after universe/forward checks")
    signal_dates = [day for day in usable_market_dates if start <= day <= end]
    industry_mapping = _load_industry()
    trading_dates = market_dates
    signal_times = [item.strip() for item in config.signal_times.split(",") if item.strip()]

    asof_parts: list[pd.DataFrame] = []
    for number, instrument in enumerate(instruments, 1):
        minutes = _read_instrument(paths_by_instrument[instrument], instrument, start, end)
        daily = daily_panel.loc[daily_panel["instrument"] == instrument].sort_values("date")
        part = _asof_rows_for_instrument(
            minutes,
            daily,
            signal_dates,
            signal_times,
            trading_dates,
            industry_mapping,
            config,
        )
        if not part.empty:
            asof_parts.append(part)
        if number == 1 or number % 50 == 0 or number == len(instruments):
            print(f"  as-of pass {number}/{len(instruments)}", flush=True)
    if not asof_parts:
        raise ValueError("No as-of feature rows")
    asof_panel = pd.concat(asof_parts, ignore_index=True, sort=False)
    cache_root.mkdir(parents=True, exist_ok=True)
    daily_panel.to_parquet(daily_path, index=False, compression="zstd")
    market.reset_index().to_parquet(market_path, index=False, compression="zstd")
    asof_panel.to_parquet(asof_path, index=False, compression="zstd")
    metadata = {
        "cache_schema": CACHE_SCHEMA_VERSION,
        "cache_reused": False,
        "instruments": len(instruments),
        "universe": config.universe,
        "universe_asof": config.universe_asof,
        "minute_files": sum(len(value) for value in paths_by_instrument.values()),
        "daily_rows": len(daily_panel),
        "asof_rows": len(asof_panel),
        "signal_dates": len(signal_dates),
        "signal_start": str(min(signal_dates)) if signal_dates else None,
        "signal_end": str(max(signal_dates)) if signal_dates else None,
        "industry_instruments": len(industry_mapping),
        "max_universe_n": max_universe_n,
        "expected_universe_n": expected_universe_n,
        "minimum_coverage": minimum_coverage,
        "fixed_universe_expected": len(allowed),
        "fixed_universe_present": len(instruments),
        "fixed_universe_missing": len(allowed.difference(instruments)),
        "min_daily_bars": config.min_daily_bars,
        "min_history_days": config.min_history_days,
    }
    cache_manifest.write_text(
        json.dumps(
            {
                "model": MODEL_NAME,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "config": expected_cache_config,
                "metadata": metadata,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return daily_panel, market, asof_panel, metadata


def _num(frame: pd.DataFrame, column: str, default: float = np.nan) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _amount_quality(value: pd.Series) -> pd.Series:
    return (1.0 - np.log(value.clip(0.25, 8.0) / 1.15).abs() / np.log(8.0)).clip(0.0, 1.0)


def _market_state(prior: pd.DataFrame, current: pd.DataFrame) -> pd.Series:
    """Classify only from prior completed-day and current as-of information."""

    prior_breadth = _num(prior, "prior_breadth")
    prior_money = _num(prior, "prior_money_effect_5d", 0.0)
    current_breadth = _num(current, "market_breadth")
    current_median = _num(current, "market_median")
    current_broken = _num(current, "market_broken_ratio")
    transition = (current_breadth > prior_breadth + 0.12) & (current_median > -0.004)
    ice = (current_breadth <= -0.30) & (current_median <= -0.012)
    weak = (prior_breadth <= -0.12) & (prior_money <= 0.0) & (current_breadth < 0.05) & ~transition
    strong = (
        (current_breadth >= 0.20)
        & (current_median >= 0.003)
        & ((prior_money >= 0.002) | (prior_breadth >= 0.05))
    )
    climax = strong & ((current_broken >= 0.45) | ((current_breadth >= 0.55) & (current_median >= 0.012)))
    state = np.select(
        [ice, climax, strong, weak],
        ["ice", "climax", "strong", "weak"],
        default="neutral",
    )
    return pd.Series(state, index=current.index, dtype=object)


def _target_exposure(state: str, rebound: bool = False) -> float:
    """Pre-declared risk budget inspired by dynamic-position principles."""

    if state == "strong":
        return 0.60
    if state == "neutral":
        return 0.35
    if state == "climax":
        return 0.20
    if state == "weak":
        return 0.12
    if state == "ice" and rebound:
        return 0.12
    return 0.0


def _score_snapshots(
    asof: pd.DataFrame,
    market: pd.DataFrame,
    profile: str | RuleProfile | None = None,
) -> pd.DataFrame:
    profile = _resolve_profile(profile)
    frame = asof.copy()
    frame["signal_date"] = pd.to_datetime(frame["signal_date"]).dt.normalize()
    frame["cutoff"] = frame["cutoff"].astype(str)
    key = ["signal_date", "cutoff"]
    returns = _num(frame, "intraday_return")
    frame["rank_intraday"] = returns.groupby([frame[item] for item in key]).rank(pct=True)
    frame["rank_prior10"] = _num(frame, "prior_ret10").groupby([frame[item] for item in key]).rank(pct=True)
    frame["rank_recovery"] = _num(frame, "recovery_from_low").groupby([frame[item] for item in key]).rank(pct=True)
    frame["rank_amount"] = _num(frame, "amount_ratio_asof").groupby([frame[item] for item in key]).rank(pct=True)

    market_current = frame.groupby(key, sort=False).agg(
        market_n=("instrument", "nunique"),
        market_breadth=("intraday_return", lambda s: float((s > 0).mean() - (s < 0).mean())),
        market_median=("intraday_return", "median"),
        market_up_ratio=("intraday_return", lambda s: float((s > 0.02).mean())),
        market_down_ratio=("intraday_return", lambda s: float((s < -0.02).mean())),
        market_locked_count=("locked_upper", "sum"),
        market_touched_count=("touched_upper", "sum"),
        market_broken_count=("broken_upper", "sum"),
    ).reset_index()
    market_current["market_broken_ratio"] = market_current["market_broken_count"] / market_current["market_touched_count"].clip(lower=1)
    market_current["market_board_quality"] = market_current["market_locked_count"] / market_current["market_touched_count"].clip(lower=1)
    market_current["collective_oversold"] = (market_current["market_breadth"] < -0.20) & (market_current["market_median"] < -0.008)
    market_current["market_transition"] = False
    market_current["prior_breadth"] = np.nan
    market_current["prior_money_effect_5d"] = np.nan
    market_current["prior_market_ret5"] = np.nan
    market_current["prior_market_ret10"] = np.nan
    market_current["prior_universe_n"] = np.nan
    market_lookup = market.copy()
    market_lookup.index = pd.to_datetime(market_lookup.index).normalize()
    for idx, row in market_current.iterrows():
        date = pd.Timestamp(row["signal_date"])
        prior_rows = market_lookup.loc[market_lookup.index < date]
        if prior_rows.empty:
            continue
        prior = prior_rows.iloc[-1]
        market_current.at[idx, "prior_breadth"] = float(prior.get("breadth", np.nan))
        market_current.at[idx, "prior_money_effect_5d"] = float(prior.get("money_effect_5d", 0.0))
        market_current.at[idx, "prior_market_ret5"] = float(prior_rows["ret_median"].tail(5).mean())
        market_current.at[idx, "prior_market_ret10"] = float(prior_rows["ret_median"].tail(10).mean())
        market_current.at[idx, "prior_universe_n"] = float(prior.get("universe_n", np.nan))
    market_current["market_transition"] = (
        market_current["market_breadth"] > market_current["prior_breadth"] + 0.12
    ) & (market_current["market_median"] > -0.004)
    market_current["market_state"] = _market_state(market_current, market_current)
    frame = frame.merge(market_current, on=key, how="left", validate="many_to_one")

    group_keys = key + ["industry_code"]
    group = frame.groupby(group_keys, sort=False, dropna=False)
    group_stats = group.agg(
        group_n=("instrument", "nunique"),
        group_breadth=("intraday_return", lambda s: float((s > 0).mean() - (s < 0).mean())),
        group_return_median=("intraday_return", "median"),
        group_amount_median=("amount_ratio_asof", "median"),
        group_prior10_median=("prior_ret10", "median"),
    ).reset_index()
    group_stats["group_relative_return"] = group_stats["group_return_median"] - group_stats.groupby(key)["group_return_median"].transform("median")
    frame = frame.merge(group_stats, on=group_keys, how="left", validate="many_to_one")
    frame["group_intraday_rank"] = _num(frame, "intraday_return").groupby(
        [frame[item] for item in group_keys]
    ).rank(pct=True)
    frame["group_prior10_rank"] = _num(frame, "prior_ret10").groupby(
        [frame[item] for item in group_keys]
    ).rank(pct=True)
    frame["leader_rank"] = (
        0.45 * frame["group_intraday_rank"].fillna(0.0)
        + 0.25 * frame["rank_intraday"].fillna(0.0)
        + 0.20 * frame["group_prior10_rank"].fillna(0.0)
        + 0.10 * frame["rank_amount"].fillna(0.0)
    )

    frame["group_attack"] = (
        (frame["industry_code"].astype(str) != "UNKNOWN")
        & (frame["group_n"] >= profile.group_n)
        & (frame["group_breadth"] >= profile.group_breadth)
        & (frame["group_return_median"] >= profile.group_return)
        & (frame["group_relative_return"] >= profile.group_relative)
        & (frame["group_amount_median"] >= profile.group_amount)
    )
    prior_strength = (
        (_num(frame, "prior_ret10") >= profile.prior_ret10)
        | (_num(frame, "prior_limit_up5") >= profile.prior_limit_up5)
    )
    no_chase = (
        (_num(frame, "intraday_return") < profile.no_chase_return)
        & (_num(frame, "gap_to_upper") < -0.001)
    )
    amount_ok = _num(frame, "amount_ratio_asof").between(profile.amount_low, profile.amount_high)
    risk_gate = ~frame["market_state"].isin(["ice", "climax"])
    rebound = frame["market_transition"] & frame["collective_oversold"] & frame["group_attack"]
    risk_gate = risk_gate | rebound
    trend = (
        frame["group_attack"] & prior_strength & no_chase & amount_ok
        & _num(frame, "intraday_return").between(profile.trend_return_low, profile.trend_return_high)
        & (_num(frame, "from_open") > profile.trend_from_open)
        & (_num(frame, "late_momentum_30m") > profile.trend_late_momentum)
        & (frame["leader_rank"] >= profile.trend_leader)
    )
    pullback = (
        frame["group_attack"] & prior_strength & no_chase & amount_ok
        & _num(frame, "from_high").between(profile.pullback_from_high_low, profile.pullback_from_high_high)
        & (_num(frame, "recovery_from_low") > profile.pullback_recovery)
        & (_num(frame, "late_momentum_30m") > profile.pullback_late_momentum)
        & (frame["leader_rank"] >= profile.pullback_leader)
    )
    reseal = (
        frame["group_attack"] & prior_strength & no_chase & amount_ok
        & frame["broken_upper"]
        & _num(frame, "gap_to_upper").between(profile.reseal_gap_low, profile.reseal_gap_high)
        & (_num(frame, "late_momentum_30m") > profile.reseal_late_momentum)
        & (frame["leader_rank"] >= profile.reseal_leader)
    )
    rebound_setup = (
        rebound & amount_ok
        & _num(frame, "from_high").between(profile.rebound_from_high_low, profile.rebound_from_high_high)
        & (_num(frame, "recovery_from_low") > profile.rebound_recovery)
        & (_num(frame, "late_momentum_30m") > profile.rebound_late_momentum)
        & (frame["leader_rank"] >= profile.rebound_leader)
    )
    environment_ok = pd.Series(True, index=frame.index)
    if profile.market_policy == "weak_only":
        environment_ok = frame["market_state"].eq("weak")
    elif profile.market_policy == "weak_or_ice_rebound":
        environment_ok = frame["market_state"].eq("weak") | (
            frame["market_state"].eq("ice") & rebound
        )
    trigger = (
        risk_gate
        & environment_ok
        & ~frame["locked_upper"]
        & (trend | pullback | reseal | rebound_setup)
    ).fillna(False)
    frame["trigger"] = trigger.astype(bool)
    frame["mode"] = np.select(
        [reseal, pullback, rebound_setup, trend],
        ["re_seal_confirmation", "strong_pullback_confirmation", "panic_transition_rebound", "right_side_mainline"],
        default="no_trade",
    )
    frame["reason"] = np.select(
        [reseal, pullback, rebound_setup, trend],
        [
            "主线同步+炸板回封/近板换手，下一根K线才是成交确认",
            "人气核心回撤后重新转强，板块与承接同步",
            "指数/市场情绪从极端弱势转稳，只做主线核心的小仓位反弹",
            "主线扩散、龙头排序和右侧量价同时确认",
        ],
        default="NO_TRADE",
    )
    frame["target_exposure"] = [
        _target_exposure(str(state), bool(reb)) for state, reb in zip(frame["market_state"], rebound)
    ]
    frame["score"] = (
        0.30 * frame["leader_rank"].fillna(0.0)
        + 0.18 * frame["group_breadth"].clip(-1.0, 1.0).add(1.0).div(2.0).fillna(0.0)
        + 0.16 * frame["rank_prior10"].fillna(0.0)
        + 0.14 * frame["rank_recovery"].fillna(0.0)
        + 0.12 * frame["rank_intraday"].fillna(0.0)
        + 0.10 * _amount_quality(frame["amount_ratio_asof"].fillna(1.0))
    )
    frame.loc[~frame["trigger"], "score"] = -np.inf
    return frame


def _select_signals(scored: pd.DataFrame, top_n: int) -> pd.DataFrame:
    candidates = scored.loc[scored["trigger"]].copy()
    if candidates.empty:
        return candidates
    candidates = candidates.sort_values(["signal_date", "instrument", "signal_datetime", "score"])
    # The earliest valid opportunity wins for a stock/day; this prevents a
    # later, hindsight-better bar from replacing the first actionable one.
    candidates = candidates.drop_duplicates(["signal_date", "instrument"], keep="first")
    selected: list[pd.DataFrame] = []
    for date, group in candidates.groupby("signal_date", sort=True):
        selected.append(group.sort_values(["score", "signal_datetime"], ascending=[False, True]).head(top_n))
    if not selected:
        return pd.DataFrame()
    return pd.concat(selected, ignore_index=True).sort_values(
        ["signal_date", "signal_datetime", "score"], ascending=[True, True, False]
    ).reset_index(drop=True)


def _summary(values: pd.Series) -> dict[str, Any]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {"count": 0, "mean": None, "median": None, "win_rate": None, "worst": None, "best": None}
    return {
        "count": int(len(clean)),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "win_rate": float((clean > 0).mean()),
        "worst": float(clean.min()),
        "best": float(clean.max()),
    }


def _max_drawdown(equity: pd.Series) -> float | None:
    if equity.empty:
        return None
    return float((equity / equity.cummax() - 1.0).min())


def _portfolio(trades: pd.DataFrame, return_column: str, target_column: str = "target_exposure") -> dict[str, Any]:
    """Non-overlapping batches with unfilled orders retaining their cash."""

    if trades.empty:
        return {"batches": 0, "total_return": None, "cagr": None, "max_drawdown": None}
    rows = trades.sort_values(["signal_date", "signal_datetime", "score"], ascending=[True, True, False])
    batches: list[dict[str, Any]] = []
    next_available = pd.Timestamp.min
    for date, group in rows.groupby("signal_date", sort=True):
        date = pd.Timestamp(date).normalize()
        if date <= next_available:
            continue
        selected = group.head(20).copy()
        target = float(selected[target_column].iloc[0]) if target_column in selected else 1.0
        if target <= 0:
            continue
        valid = selected.loc[selected.get("entry_filled", False).astype(bool) & selected[return_column].notna()]
        contribution = float(target / max(1, len(selected)) * valid[return_column].sum()) if not valid.empty else 0.0
        exit_dates = []
        exit_col = "dynamic_exit_date" if return_column == "dynamic_return" else return_column.replace("return_", "exit_") + "_date"
        if exit_col in valid:
            exit_dates = [pd.Timestamp(item).normalize() for item in valid[exit_col].dropna()]
        exit_date = max(exit_dates) if exit_dates else date
        batches.append(
            {
                "signal_date": date,
                "exit_date": exit_date,
                "selected": int(len(selected)),
                "filled": int(len(valid)),
                "target_exposure": target,
                "return": contribution,
                "instruments": selected["instrument"].astype(str).tolist(),
            }
        )
        next_available = exit_date
    if not batches:
        return {"batches": 0, "total_return": 0.0, "cagr": None, "max_drawdown": None}
    equity = 1.0
    curve: list[dict[str, Any]] = []
    for batch in batches:
        equity *= 1.0 + batch["return"]
        curve.append({"date": batch["exit_date"], "equity": equity, "return": batch["return"]})
    first_date = batches[0]["signal_date"]
    last_date = batches[-1]["exit_date"]
    years = max((last_date - first_date).days / 365.25, 1 / 365.25)
    total_return = equity - 1.0
    reliable = bool(years >= 0.5 and len(batches) >= 30)
    cagr = float(equity ** (1.0 / years) - 1.0) if reliable and equity > 0 else None
    realised = pd.Series([item["return"] for item in batches], dtype=float)
    sharpe = float(realised.mean() / realised.std(ddof=1) * math.sqrt(len(realised) / years)) if reliable and realised.std(ddof=1) > 0 else None
    return {
        "batches": int(len(batches)),
        "first_signal_date": str(first_date.date()),
        "last_exit_date": str(last_date.date()),
        "years": float(years),
        "total_return": float(total_return),
        "cagr": cagr,
        "annualization_reliable": reliable,
        "annualization_note": None if reliable else "需要至少0.5年且30个非重叠批次；否则不把短样本年化",
        "max_drawdown": _max_drawdown(pd.Series([item["equity"] for item in curve], dtype=float)),
        "event_sharpe_annualized": sharpe,
        "win_rate": float((realised > 0).mean()),
        "average_batch_return": float(realised.mean()),
        "average_target_exposure": float(np.mean([item["target_exposure"] for item in batches])),
        "average_fill_count": float(np.mean([item["filled"] for item in batches])),
        "curve": [
            {"date": str(item["date"].date()), "equity": float(item["equity"]), "return": float(item["return"])}
            for item in curve
        ],
    }


def _period_report(trades: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    part = trades.loc[
        pd.to_datetime(trades["signal_date"]).between(start, end)
        & trades["entry_filled"].astype(bool)
    ]
    return {
        "start": str(start.date()),
        "end": str(end.date()),
        "signals": int(len(part)),
        "dynamic_return": _summary(part["dynamic_return"] if "dynamic_return" in part else pd.Series(dtype=float)),
        "t1_return": _summary(part["return_1d"] if "return_1d" in part else pd.Series(dtype=float)),
    }


def run(config: Config) -> dict[str, Any]:
    daily, market, asof, cache_meta = build_cache(config)
    profile = _resolve_profile(config.profile)
    scored = _score_snapshots(asof, market, profile)
    signals = _select_signals(scored, max(1, config.top_n))
    if signals.empty:
        raise ValueError("No signal survived the pre-declared state-machine rules")
    dynamic = _portfolio(signals, "dynamic_return", "target_exposure")
    fixed = _portfolio(signals.assign(target_exposure=1.0), "dynamic_return", "target_exposure")
    t1 = _portfolio(signals, "return_1d", "target_exposure")
    signal_dates = pd.to_datetime(signals["signal_date"]).dt.normalize().drop_duplicates().sort_values()
    split = signal_dates.iloc[max(0, len(signal_dates) * 3 // 5 - 1)] if len(signal_dates) >= 5 else signal_dates.iloc[-1]
    periods = {
        "development_first_60pct": _period_report(signals, signal_dates.iloc[0], split),
        "out_of_sample_last_40pct": _period_report(signals, split + pd.Timedelta(days=1), signal_dates.iloc[-1]),
    }
    state_report = (
        signals.groupby("market_state")["dynamic_return"].agg(
            count="count", mean="mean", median="median", win_rate=lambda s: float((s > 0).mean())
        ).reset_index().to_dict("records")
    )
    mode_report = (
        signals.groupby("mode")["dynamic_return"].agg(
            count="count", mean="mean", median="median", win_rate=lambda s: float((s > 0).mean())
        ).reset_index().to_dict("records")
    )
    source_counts = {str(k): int(v) for k, v in asof["instrument"].value_counts().describe().to_dict().items()} if not asof.empty else {}
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": f"{MODEL_NAME}:{profile.name}",
        "config": asdict(config),
        "research_status": "research_proxy_not_investment_advice",
        "methodology": {
            "principle": "环境许可 -> 主线/行业群体扩散 -> 龙头排序 -> 右侧或分歧再转强 -> 下一根5分钟K线成交",
            "environment": "上一完整交易日的市场广度/涨停赚钱效应，加当前截面的广度、涨跌幅中位数、炸板代理；defensive_rebound只在退潮/冰点中的弱市或冰点转稳时观察",
            "main_line": "CSRC行业快照的点时行业群体代理；至少4只、群体广度/中位数/量能和相对强度同时成立",
            "leader": "当前涨幅分位、行业内涨幅分位、先前10日强度、量能分位的固定加权排序",
            "entry": "只在非一字、未锁板的可观察状态触发，成交价为信号时间之后第一根5分钟K线开盘；下一根锁板/跌停标记未成交",
            "exit": "默认短线规则：下一交易日首根K线收盘后判断强弱，并在其后的下一根K线开盘退出；只有明显强势才允许观察至第二日首根K线，最多两日动态兑现；另报T+1开盘诊断",
            "position": "强势0.60、震荡0.35、退潮0.12、高潮0.20、冰点0；冰点只有指数/市场/主线同步转稳才给0.12",
            "no_lookahead": [
                "每日先由分钟K线重建完整日线；信号日只使用严格早于信号日的完整日线",
                "行业映射只取snapshot_date<=signal_date的最近快照",
                "盘中横截面只聚合datetime<=cutoff的K线",
                "买入使用cutoff之后第一根K线；锁板不强行成交",
                "动态退出只使用逐根K线已经收盘的信息；退出字段不参与信号触发、排序或仓位",
            ],
            "anti_overfit": [
                "阈值由书中反复出现的主线、合力、换手、强弱、空仓和止损原则预先固定",
                "不以任何单只股票、单个日期或测试期收益反向选择阈值",
                "同时报告固定满仓对照、动态仓位、样本外时间段、市场状态和交易模式切片",
                "短样本或批次数不足时不年化",
            ],
            "profile": {
                "name": profile.name,
                "library": sorted(PROFILE_LIBRARY),
                "selection_rule": "若用于模型选择，只允许在前60%开发段比较，最后40%固定样本外验收",
            },
        },
        "data_quality": {
            **cache_meta,
            "daily_start": str(pd.to_datetime(daily["date"]).min()) if not daily.empty else None,
            "daily_end": str(pd.to_datetime(daily["date"]).max()) if not daily.empty else None,
            "asof_rows": int(len(asof)),
            "asof_instruments": int(asof["instrument"].nunique()),
            "asof_signal_dates": int(asof["signal_date"].nunique()),
            "asof_rows_per_instrument_summary": source_counts,
            "industry_known_ratio": float((asof["industry_code"].astype(str) != "UNKNOWN").mean()),
            "survivorship_note": "固定起始CSI800股票池；未声称为无幸存者偏差全市场结果",
        },
        "headline": {
            "signals": int(len(signals)),
            "signal_days": int(signals["signal_date"].nunique()),
            "fill_rate": float(signals["entry_filled"].mean()),
            "dynamic_event_returns": _summary(signals.loc[signals["entry_filled"], "dynamic_return"]),
            "t1_event_returns": _summary(signals.loc[signals["entry_filled"], "return_1d"]),
            "dynamic_portfolio": dynamic,
            "fixed_full_exposure_control": fixed,
            "t1_dynamic_position_control": t1,
        },
        "walk_forward": periods,
        "by_market_state": _safe_json(state_report),
        "by_mode": _safe_json(mode_report),
        "signals": [
            {
                key: _safe_json(value)
                for key, value in row.items()
                if key in {
                    "instrument", "signal_date", "cutoff", "signal_datetime", "industry_code", "market_state",
                    "target_exposure", "mode", "reason", "score", "group_n", "group_breadth",
                    "group_return_median", "group_relative_return", "leader_rank", "intraday_return",
                    "from_high", "late_momentum_30m", "amount_ratio_asof", "entry_filled", "entry_reason",
                    "entry_datetime", "entry_open", "dynamic_filled", "dynamic_return", "dynamic_exit_date",
                    "dynamic_exit_reason", "return_1d", "return_2d", "return_5d",
                }
            }
            for row in signals.to_dict("records")
        ],
    }
    output = Path(config.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_safe_json(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(_safe_json({"headline": result["headline"], "walk_forward": periods}), ensure_ascii=False, indent=2))
    print(f"result: {output}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Long-sample leakage-safe public-uzi state-machine replay")
    parser.add_argument("--start", default=Config.start)
    parser.add_argument("--end", default=Config.end)
    parser.add_argument(
        "--universe",
        choices=["csi300_start", "csi500_start", "csi800_start"],
        default=Config.universe,
    )
    parser.add_argument("--universe-asof", default=Config.universe_asof)
    parser.add_argument("--signal-times", default=Config.signal_times)
    parser.add_argument("--top-n", type=int, default=Config.top_n)
    parser.add_argument("--min-daily-bars", type=int, default=Config.min_daily_bars)
    parser.add_argument("--min-history-days", type=int, default=Config.min_history_days)
    parser.add_argument("--max-instruments", type=int, default=Config.max_instruments)
    parser.add_argument("--profile", choices=sorted(PROFILE_LIBRARY), default=Config.profile)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--output", default=Config.output)
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    config = Config(
        start=args.start,
        end=args.end,
        universe=args.universe,
        universe_asof=args.universe_asof,
        signal_times=args.signal_times,
        top_n=max(1, args.top_n),
        min_daily_bars=max(20, args.min_daily_bars),
        min_history_days=max(10, args.min_history_days),
        max_instruments=max(0, args.max_instruments),
        profile=args.profile,
        refresh_cache=bool(args.refresh_cache),
        output=args.output,
    )
    return run(config)


if __name__ == "__main__":
    main()
