"""Leakage-safe intraday replay for five public short-term trading styles.

This is a research proxy, not a claim to reproduce private trading rules or
historical decisions.  The five skill documents are converted into explicit
conditions that can be evaluated at a timestamp:

* 炒股养家: market/emotion gate + leader divergence/recovery;
* 职业炒手: trend and strength only when the market is not weak;
* Asking: rhythm, pullback/retest and late recovery;
* 赵老哥: leader/relative-strength confirmation with a cohort proxy;
* 冷狐冲: board proximity and limit-up execution under a healthy atmosphere.

No end-of-day limit-up pool field is used as an intraday feature.  The board
state is reconstructed from minute bars available at the cutoff.  A signal at
T can only enter on the first bar strictly after T.  The final output includes
both event statistics and a non-overlapping batch portfolio so that a small
sample is not presented as a fictitious annual return.

Typical run after ``eastmoney_recent_backfill.py``:

    .venv\\Scripts\\python.exe five_experts_intraday_backtest.py \
        --start 20260710 --end 20260824 --top-n 5
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from config import OUTPUT_DIR, PROJECT_ROOT


MINUTE_DIR = PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "equity_5min"
BAOSTOCK_MINUTE_DIR = PROJECT_ROOT / "data_lake" / "raw" / "baostock" / "equity_5min"


@dataclass(frozen=True)
class BacktestConfig:
    start: str = "20260710"
    end: str = ""
    top_n: int = 5
    min_history_days: int = 10
    min_daily_bars: int = 40
    signal_times: str = "09:45,10:15,10:45,13:30,14:00,14:30"
    open_cost: float = 0.0003
    close_cost: float = 0.0013
    max_files: int = 0
    universe: str = "cached"


STYLE_NAMES = (
    "yangjia",
    "zhiye",
    "asking",
    "zhao",
    "lenghuchong",
)


def _date(value: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"invalid date: {value}")
    return parsed.normalize()


def _instrument_code(instrument: str) -> str:
    return str(instrument).upper().replace("SH", "").replace("SZ", "").replace("BJ", "")


def limit_ratio(instrument: str) -> float:
    """Static exchange-band proxy; ST status is intentionally not guessed."""

    code = _instrument_code(instrument)
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    if code.startswith(("4", "8", "920")):
        return 0.30
    return 0.10


def _round_tick(value: pd.Series | float) -> pd.Series | float:
    return np.round(np.asarray(value, dtype=float) / 0.01) * 0.01


def _numeric(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def csi800_members_asof(asof: pd.Timestamp) -> set[str]:
    """Return the fixed CSI800 membership active at the replay start date."""

    import qlib
    from qlib.constant import REG_CN
    from qlib.data import D
    from config import QLIB_DATA_DIR

    qlib.init(provider_uri=str(QLIB_DATA_DIR), region=REG_CN)
    mapping = D.list_instruments(instruments=D.instruments(market="csi800"), as_list=False)
    return {
        str(instrument).upper()
        for instrument, intervals in mapping.items()
        if any(start.normalize() <= asof <= end.normalize() for start, end in intervals)
    }


def load_minutes(
    start: pd.Timestamp,
    end: pd.Timestamp,
    max_files: int = 0,
    instruments: set[str] | None = None,
) -> pd.DataFrame:
    """Load cached minute bars, retaining history needed for prior features."""

    allowed = {str(item).upper() for item in instruments} if instruments is not None else None
    eastmoney_paths = sorted(
        path for path in MINUTE_DIR.glob("*.parquet") if allowed is None or path.stem.upper() in allowed
    )
    baostock_paths = sorted(
        path for path in BAOSTOCK_MINUTE_DIR.glob("*.parquet") if allowed is None or path.stem.upper() in allowed
    )
    if max_files:
        eastmoney_paths = eastmoney_paths[:max_files]
    if not eastmoney_paths and not baostock_paths:
        raise FileNotFoundError(f"No minute files under {MINUTE_DIR} or {BAOSTOCK_MINUTE_DIR}")
    load_start = start - pd.Timedelta(days=70)
    # Existing current_yangjia runs also left a small Sina/AKShare cache.  It
    # is retained as an explicitly lower-priority fallback for instruments that
    # Eastmoney rate-limited; Eastmoney rows are appended later and therefore
    # win on duplicate (instrument, datetime) keys.
    frames: list[pd.DataFrame] = []
    columns = [
        "instrument",
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    fallback_root = PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "current" / "minute_sina"
    fallback_rows = 0
    for path in sorted(fallback_root.glob("*.parquet")):
        try:
            fallback = pd.read_parquet(path, columns=["datetime", "open", "high", "low", "close", "volume", "amount"])
        except Exception:
            continue
        if fallback.empty:
            continue
        code = path.stem.upper()
        if code.startswith("SH") or code.startswith("SZ"):
            instrument = code
        else:
            instrument = f"SH{code}" if code.startswith("6") else f"SZ{code}"
        if allowed is not None and instrument not in allowed:
            continue
        fallback.insert(0, "instrument", instrument)
        fallback["source"] = "sina_5min_via_akshare"
        fallback["_source_priority"] = 1
        fallback["datetime"] = pd.to_datetime(fallback["datetime"], errors="coerce")
        fallback = fallback.loc[fallback["datetime"].between(load_start, end + pd.Timedelta(days=1))].copy()
        if fallback.empty:
            continue
        fallback = _numeric(fallback, columns[2:])
        frames.append(fallback)
        fallback_rows += len(fallback)

    source_paths = [("baostock", path) for path in baostock_paths] + [
        ("eastmoney", path) for path in eastmoney_paths
    ]
    for number, (namespace, path) in enumerate(source_paths, 1):
        try:
            try:
                frame = pd.read_parquet(path, columns=columns + ["source"])
            except Exception:
                frame = pd.read_parquet(path, columns=columns)
        except Exception:
            continue
        if frame.empty:
            continue
        if "source" not in frame:
            frame["source"] = "baostock_5min" if namespace == "baostock" else "eastmoney_cached"
        frame["source"] = frame["source"].fillna(
            "baostock_5min" if namespace == "baostock" else "eastmoney_cached"
        ).astype(str)
        frame["_source_priority"] = frame["source"].map(
            lambda value: 3 if value.startswith("eastmoney") else 2 if value.startswith("baostock") else 1
        )
        frame["instrument"] = frame["instrument"].astype(str).str.upper()
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
        frame = frame.loc[frame["datetime"].between(load_start, end + pd.Timedelta(days=1))].copy()
        if frame.empty:
            continue
        frame = _numeric(frame, columns[2:])
        frames.append(frame)
        if number == 1 or number % 250 == 0:
            print(
                f"  load minute files {number}/{len(source_paths)} "
                f"rows={sum(len(item) for item in frames)}",
                flush=True,
            )
    if not frames:
        raise ValueError("No usable minute rows in requested interval")
    result = pd.concat(frames, ignore_index=True)
    result = (
        result.dropna(subset=["instrument", "datetime", "open", "high", "low", "close"])
        .sort_values(["instrument", "datetime", "_source_priority"])
        .drop_duplicates(["instrument", "datetime"], keep="last")
        .drop(columns=["_source_priority"], errors="ignore")
        .sort_values(["instrument", "datetime"])
        .reset_index(drop=True)
    )
    source_counts = {
        str(key): int(value)
        for key, value in result["source"].value_counts(dropna=False).items()
    }
    print(
        f"  minute panel rows={len(result):,} instruments={result['instrument'].nunique()} "
        f"range={result['datetime'].min()}..{result['datetime'].max()} "
        f"(Sina fallback rows loaded={fallback_rows:,}; source rows={source_counts})",
        flush=True,
    )
    return result


def build_daily_features(minutes: pd.DataFrame, min_daily_bars: int) -> pd.DataFrame:
    """Build only completed daily rows; current partial days never enter this table."""

    frame = minutes.copy()
    frame["date"] = frame["datetime"].dt.normalize()
    daily = (
        frame.sort_values(["instrument", "datetime"])
        .groupby(["instrument", "date"], sort=True)
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
    daily["limit_ratio"] = daily["instrument"].map(limit_ratio)
    daily["prev_close"] = daily.groupby("instrument")["close"].shift(1)
    daily["upper_limit"] = _round_tick(daily["prev_close"] * (1.0 + daily["limit_ratio"]))
    daily["lower_limit"] = _round_tick(daily["prev_close"] * (1.0 - daily["limit_ratio"]))
    daily["limit_touched"] = daily["high"] >= daily["upper_limit"] - 0.011
    daily["limit_locked"] = (
        (daily["close"] >= daily["upper_limit"] - 0.011)
        & (daily["low"] >= daily["upper_limit"] - 0.011)
    )
    daily["ret1"] = daily["close"] / daily["prev_close"] - 1.0
    grouped = daily.groupby("instrument", group_keys=False)
    for window in (5, 10, 20):
        daily[f"ret{window}"] = grouped["close"].transform(lambda s: s / s.shift(window) - 1.0)
        daily[f"amount_prev{window}"] = grouped["amount"].transform(
            lambda s: s.shift(1).rolling(window, min_periods=max(3, window // 2)).mean()
        )
    daily["vol10"] = grouped["ret1"].transform(lambda s: s.rolling(10, min_periods=7).std())
    daily["prior_limit_up5"] = grouped["limit_touched"].transform(
        lambda s: s.shift(1).rolling(5, min_periods=2).sum()
    )
    daily["prior_locked_up5"] = grouped["limit_locked"].transform(
        lambda s: s.shift(1).rolling(5, min_periods=2).sum()
    )
    return daily.sort_values(["instrument", "date"]).reset_index(drop=True)


def load_event_summary() -> pd.DataFrame:
    """Load only prior-day event counts; never use the same day's final pool.

    The direct Eastmoney recent-event cache and the older current snapshots may
    contain the same date.  Taking the maximum count avoids double counting
    without treating an end-of-day pool as an intraday observation.
    """

    roots = {
        "limit_up": [
            PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "current" / "limit_up_pool",
            PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "recent_events" / "limit_up",
        ],
        "previous_limit_up": [
            PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "current" / "previous_limit_up_pool",
            PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "recent_events" / "previous_limit_up",
        ],
        "limit_down": [
            PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "current" / "limit_down_pool",
            PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "recent_events" / "limit_down",
        ],
        "broken_board": [
            PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "current" / "broken_board_pool",
            PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "recent_events" / "broken_board",
        ],
    }
    rows: list[dict[str, Any]] = []
    for event_type, directories in roots.items():
        for directory in directories:
            for path in directory.glob("*.parquet"):
                match = pd.Series([path.stem]).str.extract(r"(\d{8})", expand=False).iloc[0]
                pool_date = pd.to_datetime(match, format="%Y%m%d", errors="coerce")
                try:
                    frame = pd.read_parquet(path)
                except Exception:
                    continue
                if "pool_date" in frame.columns and frame["pool_date"].notna().any():
                    parsed = pd.to_datetime(frame["pool_date"], format="%Y%m%d", errors="coerce")
                    pool_date = parsed.dropna().iloc[0] if parsed.notna().any() else pool_date
                if pd.isna(pool_date):
                    continue
                rows.append({"date": pd.Timestamp(pool_date).normalize(), "event_type": event_type, "count": int(len(frame))})
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows).pivot_table(index="date", columns="event_type", values="count", aggfunc="max", fill_value=0)
    for column in ("limit_up", "previous_limit_up", "limit_down", "broken_board"):
        if column not in result:
            result[column] = 0
    result["board_quality"] = result["limit_up"] / (result["limit_up"] + result["broken_board"]).clip(lower=1)
    return result.sort_index()


def _prior_rows(daily: pd.DataFrame, signal_date: pd.Timestamp) -> pd.DataFrame:
    prior = daily.loc[daily["date"] < signal_date].copy()
    if prior.empty:
        return pd.DataFrame()
    prior = prior.sort_values(["instrument", "date"]).groupby("instrument", as_index=False).tail(1)
    return prior.set_index("instrument")


def _asof_snapshot(
    minutes: pd.DataFrame,
    daily: pd.DataFrame,
    signal_date: pd.Timestamp,
    cutoff: str,
    event_summary: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Aggregate bars with datetime <= cutoff and attach only prior daily rows."""

    timestamp = pd.Timestamp(f"{signal_date:%Y-%m-%d} {cutoff}:00")
    day = minutes.loc[
        (minutes["datetime"].dt.normalize() == signal_date)
        & (minutes["datetime"] <= timestamp)
    ].copy()
    if day.empty:
        return pd.DataFrame()
    day = day.sort_values(["instrument", "datetime"])
    current = (
        day.groupby("instrument", sort=False)
        .agg(
            current_close=("close", "last"),
            day_open=("open", "first"),
            current_high=("high", "max"),
            current_low=("low", "min"),
            cum_volume=("volume", "sum"),
            cum_amount=("amount", "sum"),
            bars_asof=("datetime", "size"),
            last_bar_close=("close", "last"),
            last_bar_high=("high", "last"),
            last_bar_low=("low", "last"),
            last_datetime=("datetime", "last"),
        )
        .reset_index()
    )
    late_cutoff = timestamp - pd.Timedelta(minutes=30)
    late = day.loc[day["datetime"] <= late_cutoff].groupby("instrument")["close"].last().rename("close_30m_ago")
    current = current.join(late, on="instrument")
    current["close_30m_ago"] = current["close_30m_ago"].fillna(current["day_open"])
    prior = _prior_rows(daily, signal_date)
    if prior.empty:
        return pd.DataFrame()
    prior_columns = [
        "close", "prev_close", "ret5", "ret10", "ret20", "vol10",
        "amount_prev5", "amount_prev10", "amount_prev20", "prior_limit_up5",
        "prior_locked_up5", "limit_ratio", "upper_limit", "lower_limit",
    ]
    prior = prior[[column for column in prior_columns if column in prior]].rename(
        columns={column: f"prior_{column}" for column in prior_columns if column in prior}
    )
    current = current.join(prior, on="instrument", how="inner")
    if current.empty:
        return current

    current["limit_ratio"] = current["instrument"].map(limit_ratio)
    current["previous_close"] = current["prior_close"]
    current["upper_limit"] = _round_tick(current["previous_close"] * (1.0 + current["limit_ratio"]))
    current["lower_limit"] = _round_tick(current["previous_close"] * (1.0 - current["limit_ratio"]))
    current["intraday_return"] = current["current_close"] / current["previous_close"] - 1.0
    current["from_open"] = current["current_close"] / current["day_open"] - 1.0
    current["from_high"] = current["current_close"] / current["current_high"] - 1.0
    current["recovery_from_low"] = current["current_close"] / current["current_low"] - 1.0
    current["late_momentum_30m"] = current["current_close"] / current["close_30m_ago"] - 1.0
    current["gap_to_upper"] = current["current_close"] / current["upper_limit"] - 1.0
    current["touched_upper"] = current["current_high"] >= current["upper_limit"] - 0.011
    current["locked_upper"] = (
        (current["current_close"] >= current["upper_limit"] - 0.011)
        & (current["current_low"] >= current["upper_limit"] - 0.011)
    )
    current["broken_upper"] = current["touched_upper"] & ~current["locked_upper"]
    current["amount_ratio_asof"] = current["cum_amount"] / (
        current["prior_amount_prev5"].replace(0, np.nan)
        * (current["bars_asof"] / 48.0).clip(lower=0.20)
    )
    current["amount_ratio_asof"] = current["amount_ratio_asof"].replace([np.inf, -np.inf], np.nan)
    current["rank_intraday"] = current["intraday_return"].rank(pct=True)
    current["rank_prior10"] = current["prior_ret10"].rank(pct=True)
    current["rank_prior20"] = current["prior_ret20"].rank(pct=True)
    current["rank_liquidity"] = current["cum_amount"].rank(pct=True)
    current["rank_recovery"] = current["recovery_from_low"].rank(pct=True)
    current["rank_late"] = current["late_momentum_30m"].rank(pct=True)

    valid_return = current["intraday_return"].replace([np.inf, -np.inf], np.nan).dropna()
    if valid_return.empty:
        return pd.DataFrame()
    current["market_n"] = len(valid_return)
    current["market_breadth"] = float((valid_return > 0).mean() - (valid_return < 0).mean())
    current["market_up_ratio"] = float((valid_return > 0.02).mean())
    current["market_down_ratio"] = float((valid_return < -0.02).mean())
    current["limit_up_count"] = int(current["locked_upper"].sum())
    current["touched_upper_count"] = int(current["touched_upper"].sum())
    current["broken_board_count"] = int(current["broken_upper"].sum())
    current["limit_down_count"] = int(
        ((current["current_close"] <= current["lower_limit"] + 0.011)
         & (current["current_high"] <= current["lower_limit"] + 0.011)).sum()
    )
    touched = current["touched_upper_count"].clip(lower=1)
    current["broken_ratio"] = current["broken_board_count"] / touched
    current["board_quality"] = current["limit_up_count"] / touched
    current["prior_event_limit_up_count"] = np.nan
    current["prior_event_broken_count"] = np.nan
    current["prior_event_limit_down_count"] = np.nan
    current["prior_event_board_quality"] = np.nan
    if event_summary is not None and not event_summary.empty:
        prior_events = event_summary.loc[event_summary.index < signal_date]
        if not prior_events.empty:
            event_row = prior_events.iloc[-1]
            current["prior_event_limit_up_count"] = float(event_row.get("limit_up", np.nan))
            current["prior_event_broken_count"] = float(event_row.get("broken_board", np.nan))
            current["prior_event_limit_down_count"] = float(event_row.get("limit_down", np.nan))
            current["prior_event_board_quality"] = float(event_row.get("board_quality", np.nan))
    current["signal_date"] = signal_date
    current["cutoff"] = cutoff
    current["signal_datetime"] = timestamp
    # This assertion is intentionally close to the feature construction: it
    # catches accidental use of a later bar when this code is modified.
    if pd.Timestamp(day["datetime"].max()) > timestamp:
        raise AssertionError("as-of snapshot contains a bar after its cutoff")
    return current.reset_index(drop=True)


def build_snapshots(
    minutes: pd.DataFrame,
    daily: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    signal_times: list[str],
    event_summary: pd.DataFrame | None = None,
) -> tuple[dict[tuple[pd.Timestamp, str], pd.DataFrame], list[pd.Timestamp]]:
    full_dates = sorted(pd.Timestamp(item) for item in daily["date"].drop_duplicates())
    signal_dates = [item for item in full_dates if start <= item <= end]
    snapshots: dict[tuple[pd.Timestamp, str], pd.DataFrame] = {}
    for number, date in enumerate(signal_dates, 1):
        for cutoff in signal_times:
            snapshot = _asof_snapshot(minutes, daily, date, cutoff, event_summary)
            if not snapshot.empty:
                snapshots[(date, cutoff)] = snapshot
        if number == 1 or number % 10 == 0:
            print(f"  snapshots {number}/{len(signal_dates)}", flush=True)
    return snapshots, signal_dates


def _market_gate(frame: pd.DataFrame, style: str) -> pd.Series:
    breadth = frame["market_breadth"]
    broken = frame["broken_ratio"]
    down = frame["market_down_ratio"]
    # Event pools are only prior-day information here.  They make the
    # atmosphere gate less dependent on how many minute files happened to be
    # downloaded, while current-day breadth still comes from as-of bars.
    limitups = frame["prior_event_limit_up_count"].fillna(frame["limit_up_count"])
    event_quality = frame["prior_event_board_quality"].fillna(frame["board_quality"])
    if style == "yangjia":
        return (breadth > -0.18) & (broken <= 0.70) & (down < 0.10)
    if style == "zhiye":
        return (breadth > -0.08) & (down < 0.45) & (frame["board_quality"] >= 0.25)
    if style == "asking":
        return (breadth > -0.20) & (broken <= 0.75) & (down < 0.12)
    if style == "zhao":
        return (breadth > -0.12) & (limitups >= 15) & (down < 0.10)
    if style == "lenghuchong":
        return (
            (breadth > -0.05)
            & (limitups >= 25)
            & (event_quality >= 0.45)
            & (broken <= 0.55)
        )
    raise KeyError(style)


def _amount_quality(series: pd.Series) -> pd.Series:
    return (1.0 - np.log(series.clip(0.25, 8.0) / 1.2).abs() / np.log(8.0)).clip(0.0, 1.0)


def apply_style_rule(frame: pd.DataFrame, style: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return trigger, score and human-readable reason without future fields."""

    gate = _market_gate(frame, style)
    active = ~frame["locked_upper"]
    amount = frame["amount_ratio_asof"].between(0.45, 4.0)
    prior10 = frame["prior_ret10"]
    current = frame["intraday_return"]
    pullback = frame["from_high"]
    late = frame["late_momentum_30m"]
    recovery = frame["recovery_from_low"]
    gap = frame["gap_to_upper"]

    if style == "yangjia":
        # 分歧低吸: a prior strong/leader proxy has touched the upper band or
        # recently had a board, then pulls back but recovers before entry.
        trigger = gate & active & amount & (
            prior10 > 0.03
        ) & (
            frame["touched_upper"] | (frame["prior_prior_limit_up5"] >= 1)
        ) & pullback.between(-0.08, -0.008) & (late > -0.002) & current.between(-0.03, 0.06)
        score = (
            0.28 * frame["rank_prior10"]
            + 0.24 * frame["rank_late"]
            + 0.20 * frame["rank_recovery"]
            + 0.16 * _amount_quality(frame["amount_ratio_asof"])
            + 0.12 * frame["rank_prior20"]
        )
        reason = pd.Series("养家：主线/人气代理 + 分歧回撤 + 尾盘修复", index=frame.index)
    elif style == "zhiye":
        # 职业炒手 proxy: trend continuation, but no weak-market or overheated
        # chase.  This is deliberately stricter than raw momentum.
        trigger = gate & active & amount & (
            prior10 > 0.04
        ) & frame["from_open"].between(0.002, 0.06) & current.between(0.005, 0.065) & (
            pullback > -0.045
        ) & (frame["rank_intraday"] >= 0.60) & (frame["rank_prior10"] >= 0.55)
        score = (
            0.30 * frame["rank_intraday"]
            + 0.26 * frame["rank_prior10"]
            + 0.18 * frame["rank_prior20"]
            + 0.14 * frame["rank_liquidity"]
            + 0.12 * _amount_quality(frame["amount_ratio_asof"])
        )
        reason = pd.Series("职业炒手：顺势 + 强势环境 + 不追过热", index=frame.index)
    elif style == "asking":
        # Asking proxy: a rhythm/retest setup, requiring a late recovery instead
        # of buying a falling knife solely because it was strong earlier.
        trigger = gate & active & amount & (
            prior10 > 0.0
        ) & pullback.between(-0.08, -0.015) & (late > 0.002) & (recovery > 0.012) & (
            current.between(-0.02, 0.05)
        ) & (frame["rank_prior10"] >= 0.50)
        score = (
            0.28 * frame["rank_late"]
            + 0.25 * frame["rank_recovery"]
            + 0.20 * frame["rank_prior10"]
            + 0.15 * frame["rank_intraday"]
            + 0.12 * _amount_quality(frame["amount_ratio_asof"])
        )
        reason = pd.Series("Asking：节奏回踩 + 盘中再转强", index=frame.index)
    elif style == "zhao":
        # No point-in-time industry labels are available in the recent minute
        # cache.  The "theme" component is therefore explicitly a cohort proxy:
        # leader strength + recent board participation + turnover confirmation.
        trigger = gate & active & (
            frame["rank_intraday"] >= 0.85
        ) & (prior10 > 0.05) & current.between(0.02, 0.09) & (
            frame["amount_ratio_asof"] >= 1.10
        ) & (
            (frame["prior_prior_limit_up5"] >= 1) | frame["touched_upper"]
        ) & (gap > -0.05)
        score = (
            0.32 * frame["rank_intraday"]
            + 0.25 * frame["rank_prior10"]
            + 0.18 * frame["rank_liquidity"]
            + 0.15 * frame["rank_prior20"]
            + 0.10 * _amount_quality(frame["amount_ratio_asof"])
        )
        reason = pd.Series("赵老哥：龙头代理 + 题材合力代理 + 资金确认", index=frame.index)
    elif style == "lenghuchong":
        # Pre-seal/near-board execution.  A bar already locked at the upper
        # limit is excluded because the next-bar order is not reliably fillable.
        threshold = frame["limit_ratio"] * 0.55
        trigger = gate & active & (
            current >= threshold
        ) & (gap.between(-0.025, -0.001)) & (
            frame["current_high"] >= frame["upper_limit"] * 0.995
        ) & (frame["last_bar_high"] >= frame["upper_limit"] * 0.995) & (
            frame["from_open"] > 0.02
        )
        score = (
            0.35 * (1.0 + gap / 0.025).clip(0, 1)
            + 0.25 * frame["rank_intraday"]
            + 0.20 * frame["rank_liquidity"]
            + 0.20 * frame["rank_late"]
        )
        reason = pd.Series("冷狐冲：市场氛围 + 近板确认 + 排队成交约束", index=frame.index)
    else:
        raise KeyError(style)
    score = score.replace([np.inf, -np.inf], np.nan)
    trigger = (trigger & score.notna()).fillna(False).astype(bool)
    score = score.fillna(-np.inf)
    return trigger, score, reason


def generate_signals(
    snapshots: dict[tuple[pd.Timestamp, str], pd.DataFrame],
    top_n: int,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    signals_by_style: dict[str, pd.DataFrame] = {}
    count_rows: list[dict[str, Any]] = []
    for style in STYLE_NAMES:
        candidate_parts: list[pd.DataFrame] = []
        for (date, cutoff), frame in sorted(snapshots.items()):
            trigger, score, reason = apply_style_rule(frame, style)
            count_rows.append(
                {
                    "style": style,
                    "date": str(date.date()),
                    "cutoff": cutoff,
                    "universe_n": int(len(frame)),
                    "market_breadth": float(frame["market_breadth"].iloc[0]),
                    "limit_up_count": int(frame["limit_up_count"].iloc[0]),
                    "broken_board_count": int(frame["broken_board_count"].iloc[0]),
                    "trigger_count": int(trigger.sum()),
                }
            )
            if not trigger.any():
                continue
            part = frame.loc[trigger].copy()
            part["style"] = style
            part["score"] = score.loc[trigger]
            part["reason"] = reason.loc[trigger]
            part["signal_time"] = part["signal_datetime"]
            candidate_parts.append(part)
        if not candidate_parts:
            signals_by_style[style] = pd.DataFrame()
            continue
        candidates = pd.concat(candidate_parts, ignore_index=True)
        candidates = candidates.sort_values(["signal_date", "signal_datetime", "score"], ascending=[True, True, False])
        # One first opportunity per stock/day prevents the later, more
        # favourable-looking bar from replacing an earlier real decision.
        candidates = candidates.drop_duplicates(["signal_date", "instrument"], keep="first")
        selected_parts: list[pd.DataFrame] = []
        for date, day in candidates.groupby("signal_date", sort=True):
            remaining = day.sort_values(["signal_datetime", "score"], ascending=[True, False]).head(top_n)
            selected_parts.append(remaining)
        selected = pd.concat(selected_parts, ignore_index=True) if selected_parts else pd.DataFrame()
        signals_by_style[style] = selected.sort_values(["signal_date", "signal_datetime", "score"], ascending=[True, True, False]).reset_index(drop=True)
    return signals_by_style, count_rows


def _first_bar(frame: pd.DataFrame, date: pd.Timestamp) -> pd.Series | None:
    rows = frame.loc[frame["datetime"].dt.normalize() == date].sort_values("datetime")
    if rows.empty:
        return None
    return rows.iloc[0]


def _entry_and_exit(
    instrument_frame: pd.DataFrame,
    signal_datetime: pd.Timestamp,
    signal_date: pd.Timestamp,
    signal_previous_close: float,
    limit_ratio_value: float,
    trading_dates: list[pd.Timestamp],
    config: BacktestConfig,
) -> dict[str, Any]:
    rows = instrument_frame.sort_values("datetime")
    after = rows.loc[rows["datetime"] > signal_datetime]
    if after.empty:
        return {"entry_filled": False, "entry_reason": "no_next_bar"}
    entry_bar = after.iloc[0]
    previous_close = float(signal_previous_close)
    upper = float(_round_tick(previous_close * (1.0 + limit_ratio_value)))
    lower = float(_round_tick(previous_close * (1.0 - limit_ratio_value)))
    entry_locked_up = bool(
        entry_bar["open"] >= upper - 0.011
        and entry_bar["low"] >= upper - 0.011
        and entry_bar["high"] >= upper - 0.011
    )
    entry_locked_down = bool(
        entry_bar["open"] <= lower + 0.011
        and entry_bar["high"] <= lower + 0.011
    )
    if entry_locked_up:
        return {
            "entry_filled": False,
            "entry_reason": "next_bar_locked_up",
            "entry_datetime": entry_bar["datetime"],
            "entry_open": float(entry_bar["open"]),
        }
    if entry_locked_down:
        return {
            "entry_filled": False,
            "entry_reason": "next_bar_locked_down",
            "entry_datetime": entry_bar["datetime"],
            "entry_open": float(entry_bar["open"]),
        }
    try:
        position = trading_dates.index(signal_date)
    except ValueError:
        return {"entry_filled": False, "entry_reason": "signal_date_not_in_calendar"}
    result: dict[str, Any] = {
        "entry_filled": True,
        "entry_reason": "next_bar_open",
        "entry_datetime": entry_bar["datetime"],
        "entry_open": float(entry_bar["open"]),
    }
    # Short-term styles are often evaluated at the next session and again at
    # the second session.  Keep the older T+5 diagnostic as a longer-tail
    # check, but do not force a five-day holding interpretation onto a
    # T+1/T+2 trading idea.
    for horizon in (1, 2, 5):
        exit_pos = position + horizon
        if exit_pos >= len(trading_dates):
            result[f"exit_{horizon}d_filled"] = False
            result[f"exit_{horizon}d_reason"] = "forward_window_missing"
            result[f"exit_{horizon}d_open"] = np.nan
            continue
        exit_date = trading_dates[exit_pos]
        exit_bar = _first_bar(rows, exit_date)
        if exit_bar is None:
            result[f"exit_{horizon}d_filled"] = False
            result[f"exit_{horizon}d_reason"] = "no_exit_bar"
            result[f"exit_{horizon}d_open"] = np.nan
            continue
        previous_exit = rows.loc[rows["datetime"].dt.normalize() < exit_date]
        previous_exit_close = float(previous_exit.sort_values("datetime").iloc[-1]["close"]) if not previous_exit.empty else float(exit_bar["close"])
        exit_lower = float(_round_tick(previous_exit_close * (1.0 - limit_ratio_value)))
        locked_down = bool(
            exit_bar["open"] <= exit_lower + 0.011
            and exit_bar["high"] <= exit_lower + 0.011
            and exit_bar["low"] <= exit_lower + 0.011
        )
        result[f"exit_{horizon}d_filled"] = not locked_down
        result[f"exit_{horizon}d_reason"] = "first_bar_open" if not locked_down else "exit_locked_down"
        result[f"exit_{horizon}d_open"] = float(exit_bar["open"])
        result[f"exit_{horizon}d_date"] = exit_date
    return result


def attach_outcomes(
    signals: pd.DataFrame,
    minutes: pd.DataFrame,
    trading_dates: list[pd.Timestamp],
    config: BacktestConfig,
) -> pd.DataFrame:
    if signals.empty:
        return signals.copy()
    grouped = {instrument: frame for instrument, frame in minutes.groupby("instrument", sort=False)}
    rows: list[dict[str, Any]] = []
    for _, signal in signals.iterrows():
        item = signal.to_dict()
        frame = grouped.get(signal["instrument"])
        if frame is None:
            item["entry_filled"] = False
            item["entry_reason"] = "instrument_missing"
        else:
            outcome = _entry_and_exit(
                frame,
                pd.Timestamp(signal["signal_datetime"]),
                pd.Timestamp(signal["signal_date"]),
                float(signal["previous_close"]),
                float(signal["limit_ratio"]),
                trading_dates,
                config,
            )
            item.update(outcome)
            if outcome.get("entry_filled"):
                entry = float(outcome["entry_open"])
                for horizon in (1, 2, 5):
                    exit_price = outcome.get(f"exit_{horizon}d_open", np.nan)
                    executable = bool(outcome.get(f"exit_{horizon}d_filled", False))
                    item[f"return_{horizon}d"] = (
                        float(exit_price / entry - 1.0 - config.open_cost - config.close_cost)
                        if executable and np.isfinite(exit_price) and entry > 0
                        else np.nan
                    )
        rows.append(item)
    return pd.DataFrame(rows)


def _summary(values: pd.Series) -> dict[str, Any]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {"count": 0, "mean": None, "median": None, "win_rate": None, "worst": None, "best": None}
    return {
        "count": int(len(clean)),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "trimmed_mean": float(clean.sort_values().iloc[1:-1].mean()) if len(clean) >= 5 else None,
        "win_rate": float((clean > 0).mean()),
        "worst": float(clean.min()),
        "best": float(clean.max()),
    }


def _max_drawdown(equity: pd.Series) -> float | None:
    clean = equity.dropna()
    if clean.empty:
        return None
    return float((clean / clean.cummax() - 1.0).min())


def _portfolio_batches(
    trades: pd.DataFrame,
    horizon: int,
    full_dates: list[pd.Timestamp],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if trades.empty:
        return [], {"count": 0, "total_return": None, "cagr": None, "max_drawdown": None}
    return_column = f"return_{horizon}d"
    usable = trades.loc[trades["entry_filled"] & trades[return_column].notna()].copy()
    if usable.empty:
        return [], {"count": 0, "total_return": None, "cagr": None, "max_drawdown": None}
    usable["signal_date"] = pd.to_datetime(usable["signal_date"]).dt.normalize()
    usable[f"exit_date_{horizon}"] = usable[f"exit_{horizon}d_date"].map(pd.Timestamp)
    batches: list[dict[str, Any]] = []
    next_available = pd.Timestamp.min
    for signal_date, group in usable.groupby("signal_date", sort=True):
        if signal_date <= next_available:
            continue
        selected = group.sort_values("score", ascending=False)
        batch_return = float(selected[return_column].mean())
        exit_date = pd.Timestamp(selected[f"exit_date_{horizon}"].iloc[0])
        batches.append(
            {
                "signal_date": signal_date,
                "exit_date": exit_date,
                "selected": int(len(selected)),
                "return": batch_return,
                "instruments": selected["instrument"].astype(str).tolist(),
            }
        )
        next_available = exit_date
    if not batches:
        return [], {"count": 0, "total_return": None, "cagr": None, "max_drawdown": None}
    equity = 1.0
    curve: list[dict[str, Any]] = []
    for batch in batches:
        equity *= 1.0 + batch["return"]
        curve.append({"date": batch["exit_date"], "equity": equity, "return": batch["return"]})
    first_date = batches[0]["signal_date"]
    last_date = batches[-1]["exit_date"]
    years = max((last_date - first_date).days / 365.25, 1.0 / 365.25)
    total_return = equity - 1.0
    raw_cagr = equity ** (1.0 / years) - 1.0
    realized = pd.Series([item["return"] for item in curve], dtype=float)
    # A two-month window with one or two batches can produce absurd annualized
    # numbers.  Keep the raw calculation out of the headline result until a
    # longer walk-forward sample is available.
    annualization_reliable = bool(years >= 0.5 and len(batches) >= 30)
    cagr = float(raw_cagr) if annualization_reliable else None
    event_sharpe = (
        float(realized.mean() / realized.std(ddof=1) * math.sqrt(len(realized) / years))
        if annualization_reliable and realized.std(ddof=1) > 0
        else None
    )
    result = {
        "count": int(len(batches)),
        "first_signal_date": str(first_date.date()),
        "last_exit_date": str(last_date.date()),
        "total_return": float(total_return),
        "cagr": None if cagr is None else float(cagr),
        "annualization_reliable": annualization_reliable,
        "annualization_note": "requires at least 0.5 years and 30 non-overlapping batches; current short window is not annualizable" if not annualization_reliable else None,
        "max_drawdown": _max_drawdown(pd.Series([item["equity"] for item in curve], dtype=float)),
        "event_sharpe_annualized": event_sharpe,
        "average_batch_return": float(realized.mean()),
        "win_rate": float((realized > 0).mean()),
        "average_wait_days": float(np.mean(np.diff([item["signal_date"].toordinal() for item in batches]))) if len(batches) >= 2 else None,
        "curve": [
            {"date": str(item["date"].date()), "equity": float(item["equity"]), "return": float(item["return"])}
            for item in curve
        ],
    }
    return batches, result


def _style_report(
    trades: pd.DataFrame,
    signal_counts: pd.DataFrame,
    full_dates: list[pd.Timestamp],
) -> dict[str, Any]:
    if trades.empty:
        return {
            "signals": 0,
            "signal_days": 0,
            "fill_rate": None,
            "rejected_entries": {},
            "returns": {
                "1d": _summary(pd.Series(dtype=float)),
                "2d": _summary(pd.Series(dtype=float)),
                "5d": _summary(pd.Series(dtype=float)),
            },
            "portfolio": {"1d": {}, "2d": {}, "5d": {}},
        }
    signal_days = pd.to_datetime(trades["signal_date"]).dt.normalize().nunique()
    rejected = trades.loc[~trades["entry_filled"], "entry_reason"].value_counts().to_dict()
    batches1, portfolio1 = _portfolio_batches(trades, 1, full_dates)
    batches2, portfolio2 = _portfolio_batches(trades, 2, full_dates)
    batches5, portfolio5 = _portfolio_batches(trades, 5, full_dates)
    return {
        "signals": int(len(trades)),
        "signal_days": int(signal_days),
        "opportunity_rate": float(signal_days / max(1, len(full_dates))),
        "fill_rate": float(trades["entry_filled"].mean()),
        "rejected_entries": {str(key): int(value) for key, value in rejected.items()},
        "returns": {
            "1d": _summary(trades.loc[trades["entry_filled"], "return_1d"]),
            "2d": _summary(trades.loc[trades["entry_filled"], "return_2d"]),
            "5d": _summary(trades.loc[trades["entry_filled"], "return_5d"]),
        },
        "portfolio": {"1d": portfolio1, "2d": portfolio2, "5d": portfolio5},
        "batch_count": {"1d": len(batches1), "2d": len(batches2), "5d": len(batches5)},
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay five short-term public-style proxies on Eastmoney 5-minute data")
    parser.add_argument("--start", default=BacktestConfig.start)
    parser.add_argument("--end", default=BacktestConfig.end, help="empty means latest completed daily bar in the cache")
    parser.add_argument("--top-n", type=int, default=BacktestConfig.top_n)
    parser.add_argument("--min-history-days", type=int, default=BacktestConfig.min_history_days)
    parser.add_argument("--min-daily-bars", type=int, default=BacktestConfig.min_daily_bars)
    parser.add_argument("--signal-times", default=BacktestConfig.signal_times)
    parser.add_argument("--max-files", type=int, default=BacktestConfig.max_files)
    parser.add_argument(
        "--universe",
        choices=["cached", "csi800_start"],
        default=BacktestConfig.universe,
        help="cached files or the fixed CSI800 membership active at the requested start date",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "five_experts_intraday_backtest_latest.json")
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    config = BacktestConfig(
        start=args.start,
        end=args.end,
        top_n=max(1, args.top_n),
        min_history_days=max(3, args.min_history_days),
        min_daily_bars=max(20, args.min_daily_bars),
        signal_times=args.signal_times,
        max_files=max(0, args.max_files),
        universe=args.universe,
    )
    requested_start = _date(config.start)
    # A finite sentinel avoids overflowing when load_minutes adds one day to
    # the requested upper bound; it is replaced by the latest completed bar
    # after the cache has been loaded.
    requested_end = _date(config.end) if config.end else pd.Timestamp("2100-01-01")
    universe_filter = csi800_members_asof(requested_start) if config.universe == "csi800_start" else None
    minutes = load_minutes(requested_start, requested_end, config.max_files, universe_filter)
    daily = build_daily_features(minutes, config.min_daily_bars)
    event_summary = load_event_summary()
    if daily.empty:
        raise ValueError("No completed daily rows")
    actual_last = pd.Timestamp(daily["date"].max())
    end = min(requested_end, actual_last)
    signal_times = [item.strip() for item in config.signal_times.split(",") if item.strip()]
    snapshots, signal_dates = build_snapshots(minutes, daily, requested_start, end, signal_times, event_summary)
    if len(signal_dates) <= config.min_history_days:
        raise ValueError(f"Too few completed signal dates: {len(signal_dates)}")
    trading_dates = sorted(pd.Timestamp(item) for item in daily["date"].drop_duplicates())
    # Reserve five future sessions for the longest evaluation horizon.
    usable_signal_dates = [item for item in signal_dates if item in trading_dates and trading_dates.index(item) + 5 < len(trading_dates)]
    snapshots = {key: value for key, value in snapshots.items() if key[0] in usable_signal_dates}
    signals_by_style, signal_count_rows = generate_signals(snapshots, config.top_n)
    reports: dict[str, Any] = {}
    trade_rows: list[dict[str, Any]] = []
    for style in STYLE_NAMES:
        signals = attach_outcomes(signals_by_style[style], minutes, trading_dates, config)
        reports[style] = _style_report(signals, pd.DataFrame(), trading_dates)
        if not signals.empty:
            trade_rows.extend(signals.to_dict("records"))
    trades = pd.DataFrame(trade_rows)
    # Keep the output compact enough to inspect, while retaining the reasons
    # and every selected candidate's execution result.
    trade_output = []
    if not trades.empty:
        for row in trades.to_dict("records"):
            trade_output.append(
                {
                    key: _json_safe(value)
                    for key, value in row.items()
                    if key
                    in {
                        "style", "instrument", "signal_date", "cutoff", "signal_datetime", "score", "reason",
                        "market_breadth", "limit_up_count", "broken_board_count", "board_quality", "intraday_return",
                        "from_high", "late_momentum_30m", "gap_to_upper", "entry_filled", "entry_reason",
                        "entry_datetime", "entry_open", "exit_1d_filled", "exit_1d_reason", "exit_1d_date", "return_1d",
                        "exit_5d_filled", "exit_5d_reason", "exit_5d_date", "return_5d",
                    }
                }
            )
    count_frame = pd.DataFrame(signal_count_rows)
    latest_market: list[dict[str, Any]] = []
    if not count_frame.empty:
        latest = count_frame.loc[count_frame["date"] == count_frame["date"].max()]
        latest_market = latest.drop_duplicates(["date", "cutoff"])[
            ["date", "cutoff", "universe_n", "market_breadth", "limit_up_count", "broken_board_count"]
        ].to_dict("records")
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": asdict(config),
        "methodology": {
            "signal": "daily prior features plus minute bars with datetime <= cutoff",
            "entry": "first five-minute bar strictly after the signal timestamp, open price",
            "exit": "T+1 and T+5 first bar open; locked-down exit marked unfilled",
            "costs": f"open {config.open_cost:.4%}, close {config.close_cost:.4%}",
            "universe": (
                "fixed CSI800 membership active at requested start date; source priority is Eastmoney > BaoStock > Sina"
                if config.universe == "csi800_start"
                else "cached Eastmoney plus BaoStock 5-minute files and Sina/AKShare fallback; source priority is Eastmoney > BaoStock > Sina"
            ),
            "yangjia": "emotion/regime gate + leader-divergence/recovery proxy",
            "zhiye": "trend/strength + weak-market avoidance proxy",
            "asking": "rhythm pullback/retest + late recovery proxy",
            "zhao": "leader/new-theme/资金合力 proxy; no point-in-time industry labels, so cohort is explicit proxy",
            "lenghuchong": "near-limit confirmation + board-atmosphere and fillability proxy",
            "no_lookahead": [
                "current-day features are aggregated only through each cutoff",
                "prior daily features use the last completed day strictly before signal_date",
                "entry uses the first bar strictly after signal_datetime",
                "end-of-day event pools are not used as intraday signals",
            ],
        },
        "data_quality": {
            "minute_rows": int(len(minutes)),
            "minute_instruments": int(minutes["instrument"].nunique()),
            "minute_start": str(minutes["datetime"].min()),
            "minute_end": str(minutes["datetime"].max()),
            "minute_source_rows": {
                str(key): int(value)
                for key, value in minutes["source"].value_counts(dropna=False).items()
            },
            "minute_source_instruments": {
                str(key): int(value)
                for key, value in minutes.groupby("source")["instrument"].nunique().items()
            },
            "universe_filter_instruments": int(len(universe_filter)) if universe_filter is not None else None,
            "completed_daily_dates": int(len(trading_dates)),
            "event_summary_dates": int(len(event_summary)) if not event_summary.empty else 0,
            "signal_dates_before_forward_reserve": int(len(signal_dates)),
            "usable_signal_dates": int(len(usable_signal_dates)),
            "usable_signal_start": str(min(usable_signal_dates)) if usable_signal_dates else None,
            "usable_signal_end": str(max(usable_signal_dates)) if usable_signal_dates else None,
        },
        "latest_market_snapshots": _json_safe(latest_market),
        "styles": reports,
        "signal_counts": _json_safe(signal_count_rows),
        "trades": trade_output,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(_json_safe(reports), ensure_ascii=False, indent=2))
    print(f"result: {args.output}")
    return result


if __name__ == "__main__":
    main()
