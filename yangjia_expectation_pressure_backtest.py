"""YJ-EP: 养家预期差 / 压力释放策略回测。

This is an explicit, testable proxy for the public ``养家心法`` material.  It is
not a claim to reproduce a discretionary trader's private process.

Signal timing
-------------
All signals are formed after the close of T and are executed at the open of
T+1.  The realised return for a target position is T+1 open -> T+2 open.  A
target is re-evaluated every trading day, which is closer to the reported
short-term / overnight style than a fixed 5 or 10 day holding period.

The implementation deliberately separates three layers:

* market sentiment: breadth, money effect, trend and limit-up/limit-down
  pressure;
* sector and stock leadership: point-in-time industry breadth, sector
  leadership and stock-vs-sector relative strength;
* execution: open-to-open returns, commissions and blocked limit orders.

No feature used for ranking reads T+1 or later.  Forward prices exist only in
the execution layer after a target has already been selected.
"""

from __future__ import annotations

import argparse
import json
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import OUTPUT_DIR, PROJECT_ROOT, QLIB_DATA_DIR
from factor_transfer_backtest import (
    RawQlibStore,
    _bootstrap_mean_ci,
    _max_drawdown,
    calendar,
)


STRATEGY_YJ_EP = "yj_ep"
STRATEGY_LEADER = "yj_leader_control"
STRATEGY_REPAIR = "yj_repair_control"
STRATEGY_BENCHMARK = "eligible_equal_weight"
STRATEGIES = [
    STRATEGY_YJ_EP,
    STRATEGY_LEADER,
    STRATEGY_REPAIR,
    STRATEGY_BENCHMARK,
]

REGIME_STRONG = "strong"
REGIME_WEAK = "weak"
REGIME_TRANSITION = "transition"

DATA_LAKE_DIR = PROJECT_ROOT / "data_lake"


@dataclass(frozen=True)
class Config:
    market: str = "csi800"
    start: str = "2015-01-05"
    end: str | None = None
    rebalance_step: int = 5
    top_n: int = 30
    max_sector_names: int = 8
    hold_buffer: int = 5
    min_price: float = 2.0
    liquidity_quantile: float = 0.20
    open_cost: float = 0.0003
    close_cost: float = 0.0013
    strong_threshold: float = 0.60
    weak_threshold: float = 0.40
    seed: int = 20260823
    bootstrap_samples: int = 5000
    use_auxiliary: bool = True


def _json_safe(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if pd.isna(value) if not isinstance(value, (list, tuple, dict)) else False:
        return None
    return value


def _safe_return(new: float, old: float) -> float:
    if not np.isfinite(new) or not np.isfinite(old) or old <= 0:
        return np.nan
    return float(new / old - 1.0)


def _mean(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    return float(finite.mean()) if finite.size else np.nan


def _std(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    return float(finite.std(ddof=0)) if finite.size >= 2 else np.nan


def _clip01(value: pd.Series | np.ndarray | float) -> pd.Series | np.ndarray | float:
    return np.clip(value, 0.0, 1.0)


def _rank(series: pd.Series, ascending: bool = True) -> pd.Series:
    result = series.rank(pct=True, ascending=ascending)
    return result.replace([np.inf, -np.inf], np.nan).fillna(0.5)


def _asof_index(dates: list[pd.Timestamp], date: pd.Timestamp) -> int:
    return bisect_right(dates, date) - 1


class PointInTimeUniverse:
    """Fast reader for Qlib interval membership files.

    ``point_in_time_members`` in the older experiment is adequate for sparse
    snapshots.  This version is used for daily signals and builds memberships
    with interval slices instead of comparing every interval to every date.
    """

    def __init__(self, market: str, dates: list[pd.Timestamp]) -> None:
        path = QLIB_DATA_DIR / "instruments" / f"{market}.txt"
        if not path.exists():
            raise FileNotFoundError(path)
        self.dates = dates
        self.date_text = [date.strftime("%Y-%m-%d") for date in dates]
        self.members: list[set[str]] = [set() for _ in dates]
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                parts = line.rstrip().split("\t")
                if len(parts) < 3:
                    continue
                instrument, start, end = parts[:3]
                left = bisect_left(self.date_text, start)
                right = bisect_right(self.date_text, end)
                for position in range(left, right):
                    self.members[position].add(instrument)

    def at(self, date_position: int) -> set[str]:
        return self.members[date_position]


class IndustrySnapshots:
    """Point-in-time industry codes from the local BaoStock snapshots."""

    def __init__(self) -> None:
        root = DATA_LAKE_DIR / "raw" / "baostock" / "industry_snapshots"
        self.maps: list[dict[str, str]] = []
        self.dates: list[pd.Timestamp] = []
        for path in sorted(root.glob("*.parquet")):
            frame = pd.read_parquet(path, columns=["snapshot_date", "instrument", "industry_code"])
            if frame.empty:
                continue
            date = pd.Timestamp(frame["snapshot_date"].iloc[0])
            mapping = (
                frame.dropna(subset=["instrument", "industry_code"])
                .drop_duplicates("instrument", keep="last")
                .set_index("instrument")["industry_code"]
                .astype(str)
                .to_dict()
            )
            self.dates.append(date)
            self.maps.append(mapping)
        if not self.dates:
            raise FileNotFoundError(f"No industry snapshots under {root}")

    def at(self, date: pd.Timestamp) -> dict[str, str]:
        position = _asof_index(self.dates, date)
        if position < 0:
            return {}
        return self.maps[position]


class AuxiliaryStore:
    """Lazy point-in-time reader for BaoStock ST and trade-status fields."""

    COLUMNS = ["date", "trade_status", "is_st"]

    def __init__(self) -> None:
        self.root = DATA_LAKE_DIR / "raw" / "baostock" / "equity_daily"
        self.cache: dict[str, pd.DataFrame | None] = {}

    def _load(self, instrument: str) -> pd.DataFrame | None:
        if instrument in self.cache:
            return self.cache[instrument]
        path = self.root / f"{instrument}.parquet"
        if not path.exists():
            self.cache[instrument] = None
            return None
        frame = pd.read_parquet(path, columns=self.COLUMNS)
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).drop_duplicates("date", keep="last").set_index("date")
        self.cache[instrument] = frame
        return frame

    def at(self, instrument: str, date: pd.Timestamp) -> tuple[float, float]:
        frame = self._load(instrument)
        if frame is None or date not in frame.index:
            return np.nan, np.nan
        row = frame.loc[date]
        return float(row["trade_status"]), float(row["is_st"])


def signal_dates(cal: pd.DatetimeIndex, config: Config) -> list[pd.Timestamp]:
    first = int(cal.searchsorted(pd.Timestamp(config.start), side="left"))
    requested_end = pd.Timestamp(config.end) if config.end else pd.Timestamp(cal[-1])
    last_requested = int(cal.searchsorted(requested_end, side="right")) - 1
    # T+1 open and T+(step+1) open are required for one holding interval.
    last = min(last_requested, len(cal) - config.rebalance_step - 2)
    if first > last:
        raise ValueError("No signal dates remain after reserving T+1/T+2")
    return [
        pd.Timestamp(cal[position])
        for position in range(first, last + 1, config.rebalance_step)
    ]


def _series_value(
    stored: tuple[int, np.ndarray] | None,
    absolute_position: int,
) -> float:
    if stored is None:
        return np.nan
    first, values = stored
    offset = absolute_position - first
    if offset < 0 or offset >= len(values):
        return np.nan
    return float(values[offset])


def _series_slice(
    stored: tuple[int, np.ndarray] | None,
    absolute_start: int,
    absolute_end: int,
) -> np.ndarray:
    if stored is None or absolute_end < absolute_start:
        return np.empty(0, dtype=float)
    first, values = stored
    left = max(absolute_start - first, 0)
    right = min(absolute_end - first + 1, len(values))
    if left >= right:
        return np.empty(0, dtype=float)
    return values[left:right]


def load_snapshot(
    date: pd.Timestamp,
    position: int,
    members: set[str],
    industry_map: dict[str, str],
    store: RawQlibStore,
    auxiliary: AuxiliaryStore | None,
    forward_sessions: int = 1,
) -> pd.DataFrame:
    """Build one T-close cross-section plus execution-only forward prices."""

    rows: list[dict[str, Any]] = []
    for instrument in members:
        stored = {
            field: store.series(instrument, field)
            for field in ("close", "open", "high", "low", "volume", "amount")
        }
        close = stored["close"]
        open_ = stored["open"]
        high = stored["high"]
        low = stored["low"]
        volume = stored["volume"]
        amount = stored["amount"]

        close_now = _series_value(close, position)
        high_now = _series_value(high, position)
        low_now = _series_value(low, position)
        volume_5 = _mean(_series_slice(volume, position - 4, position))
        volume_prior_20 = _mean(_series_slice(volume, position - 24, position - 5))
        amount_20 = _mean(_series_slice(amount, position - 19, position))
        amount_prior_20 = _mean(_series_slice(amount, position - 39, position - 20))
        close_window = _series_slice(close, position - 19, position)
        close_high_20 = np.nanmax(close_window) if np.isfinite(close_window).any() else np.nan
        close_low_20 = np.nanmin(close_window) if np.isfinite(close_window).any() else np.nan
        tr_values = []
        for relative in range(-19, 1):
            high_value = _series_value(high, position + relative)
            low_value = _series_value(low, position + relative)
            previous_value = _series_value(close, position + relative - 1)
            if (
                np.isfinite(high_value)
                and np.isfinite(low_value)
                and np.isfinite(previous_value)
                and previous_value > 0
            ):
                tr_values.append(max(high_value - low_value, abs(high_value - previous_value)) / previous_value)
        atr_20 = _mean(np.asarray(tr_values, dtype=float))
        close_location = (
            (close_now - low_now) / (high_now - low_now)
            if np.isfinite(close_now) and np.isfinite(high_now) and np.isfinite(low_now) and high_now > low_now
            else 0.5
        )
        trade_status, is_st = auxiliary.at(instrument, date) if auxiliary else (np.nan, np.nan)

        entry_open = _series_value(open_, position + 1)
        entry_high = _series_value(high, position + 1)
        entry_low = _series_value(low, position + 1)
        next_open = _series_value(open_, position + forward_sessions + 1)
        previous_close = close_now
        gap = _safe_return(entry_open, previous_close)
        locked = (
            np.isfinite(entry_open)
            and np.isfinite(entry_high)
            and np.isfinite(entry_low)
            and np.isfinite(gap)
            and np.isclose(entry_open, entry_high, rtol=1e-5, atol=1e-8)
            and np.isclose(entry_open, entry_low, rtol=1e-5, atol=1e-8)
            and abs(gap) >= 0.095
        )

        rows.append(
            {
                "instrument": instrument,
                "signal_date": date,
                "close": close_now,
                "ret_1": _safe_return(close_now, _series_value(close, position - 1)),
                "ret_3": _safe_return(close_now, _series_value(close, position - 3)),
                "ret_5": _safe_return(close_now, _series_value(close, position - 5)),
                "ret_10": _safe_return(close_now, _series_value(close, position - 10)),
                "ret_20": _safe_return(close_now, _series_value(close, position - 20)),
                "ret_60": _safe_return(close_now, _series_value(close, position - 60)),
                "amount_20": amount_20,
                "amount_acceleration": _safe_return(amount_20, amount_prior_20),
                "volume_ratio": volume_5 / volume_prior_20 if np.isfinite(volume_5) and np.isfinite(volume_prior_20) and volume_prior_20 > 0 else np.nan,
                "atr_20": atr_20,
                "close_location": close_location,
                "close_to_high_20": close_now / close_high_20 if np.isfinite(close_now) and np.isfinite(close_high_20) and close_high_20 > 0 else np.nan,
                "close_to_low_20": close_now / close_low_20 if np.isfinite(close_now) and np.isfinite(close_low_20) and close_low_20 > 0 else np.nan,
                "industry_code": industry_map.get(instrument, "UNKNOWN"),
                "trade_status": trade_status,
                "is_st": is_st,
                # These fields are execution-only and never enter ranking.
                "entry_open": entry_open,
                "next_open": next_open,
                "entry_gap": gap,
                "entry_blocked": bool(locked) or not np.isfinite(entry_open),
            }
        )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("instrument").sort_index()


def prepare_snapshot(snapshot: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Apply only T-known tradability filters and create sector features."""

    frame = snapshot.replace([np.inf, -np.inf], np.nan).copy()
    required = [
        "close", "ret_1", "ret_5", "ret_20", "amount_20", "volume_ratio",
        "close_location", "atr_20",
    ]
    frame = frame.dropna(subset=required)
    frame = frame.loc[(frame["close"] >= config.min_price) & (frame["amount_20"] > 0)].copy()
    if frame.empty:
        return frame

    liquidity_floor = frame["amount_20"].quantile(config.liquidity_quantile)
    frame = frame.loc[frame["amount_20"] >= liquidity_floor].copy()
    if config.use_auxiliary:
        # Unknown auxiliary values are retained so a missing side file does not
        # silently change the universe.  Known ST / suspended rows are excluded.
        frame = frame.loc[
            frame["is_st"].isna() | frame["is_st"].ne(1)
        ]
        frame = frame.loc[
            frame["trade_status"].isna() | frame["trade_status"].eq(1)
        ]
    if frame.empty:
        return frame

    frame["industry_code"] = frame["industry_code"].fillna("UNKNOWN").astype(str)
    frame["up_1"] = (frame["ret_1"] > 0).astype(float)
    frame["up_5"] = (frame["ret_5"] > 0).astype(float)
    grouped = frame.groupby("industry_code", sort=False, dropna=False)
    frame["sector_ret_5"] = grouped["ret_5"].transform("median")
    frame["sector_ret_20"] = grouped["ret_20"].transform("median")
    frame["sector_breadth_1"] = grouped["up_1"].transform("mean")
    frame["sector_breadth_5"] = grouped["up_5"].transform("mean")
    frame["stock_sector_rank"] = grouped["ret_5"].rank(pct=True).fillna(0.5)
    frame["sector_strength_rank"] = _rank(frame["sector_ret_5"])
    frame["sector_breadth_rank"] = _rank(frame["sector_breadth_5"])
    frame["relative_to_sector"] = frame["ret_5"] - frame["sector_ret_5"]

    frame["r_ret_1"] = _rank(frame["ret_1"])
    frame["r_ret_5"] = _rank(frame["ret_5"])
    frame["r_ret_20"] = _rank(frame["ret_20"])
    frame["r_ret_60"] = _rank(frame["ret_60"])
    frame["r_oversold_5"] = _rank(frame["ret_5"], ascending=False)
    frame["r_oversold_20"] = _rank(frame["ret_20"], ascending=False)
    frame["r_volume"] = _rank(frame["volume_ratio"])
    frame["r_amount_acceleration"] = _rank(frame["amount_acceleration"])
    frame["r_close_location"] = _rank(frame["close_location"])
    frame["r_stock_sector"] = frame["stock_sector_rank"]
    frame["r_sector_strength"] = frame["sector_strength_rank"]
    frame["r_sector_breadth"] = frame["sector_breadth_rank"]

    # Strong trend + a controlled one-day pullback = a measurable version of
    # "买在分歧".  The two clips avoid rewarding a limit-down collapse or a
    # completely exhausted trend.
    pullback_amount = _clip01((-frame["ret_1"]) / 0.08)
    trend_support = _clip01((frame["ret_20"] + 0.05) / 0.30)
    sector_support = _clip01((frame["sector_breadth_5"] - 0.25) / 0.60)
    volume_support = _clip01(frame["volume_ratio"] / 2.0)
    frame["controlled_pullback"] = (
        pullback_amount * trend_support * (0.5 + 0.5 * sector_support) * (0.5 + 0.5 * volume_support)
    )

    # Positive close + volume after a sharp drawdown = "恐慌释放后的修复".
    repair_amount = _clip01((frame["ret_1"] + 0.01) / 0.10)
    repair_not_breakdown = _clip01((frame["close_location"] - 0.25) / 0.75)
    frame["panic_repair"] = (
        0.35 * frame["r_oversold_5"]
        + 0.20 * frame["r_oversold_20"]
        + 0.20 * frame["r_ret_1"]
        + 0.15 * frame["r_close_location"]
        + 0.10 * frame["r_volume"]
    ) * (0.55 + 0.45 * repair_amount) * (0.55 + 0.45 * repair_not_breakdown)

    frame["leader_score"] = (
        0.28 * frame["r_sector_strength"]
        + 0.20 * frame["r_sector_breadth"]
        + 0.24 * frame["r_stock_sector"]
        + 0.13 * frame["r_ret_20"]
        + 0.08 * frame["r_volume"]
        + 0.07 * _rank(frame["controlled_pullback"])
    )
    # A sector can be hot while its strongest stock is already fully priced;
    # this small "gap" term allows a high-breadth, not-yet-crowded candidate
    # to compete with the obvious leader during transition days.
    expectation_gap = (
        0.45 * frame["r_sector_strength"]
        + 0.25 * frame["r_sector_breadth"]
        + 0.20 * (1.0 - frame["r_stock_sector"])
        + 0.10 * frame["r_amount_acceleration"]
    )
    frame["expectation_gap"] = expectation_gap
    frame["transition_score"] = (
        0.35 * frame["leader_score"]
        + 0.30 * frame["expectation_gap"]
        + 0.20 * frame["panic_repair"]
        + 0.15 * _rank(frame["controlled_pullback"])
    )

    # "卖出一致" proxy: extreme short-term extension, high close location and
    # an abnormal volume burst.  It is used as an exit filter, not a prediction
    # feature for buying the same stock.
    frame["consensus_exhaustion"] = (
        (frame["ret_1"] >= 0.07)
        & (frame["ret_5"] >= 0.15)
        & (frame["volume_ratio"] >= 1.50)
        & (frame["close_location"] >= 0.75)
    )
    frame["signal_eligible"] = ~frame["consensus_exhaustion"]
    return frame


def market_sentiment(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {
            "sentiment_score": 0.5,
            "advance_ratio": 0.5,
            "breadth_5": 0.5,
            "median_ret_5": 0.0,
            "median_ret_20": 0.0,
            "limit_up_proxy": 0.0,
            "limit_down_proxy": 0.0,
            "weak_ratio": 0.0,
            "volume_expansion": 1.0,
        }
    ret_1 = frame["ret_1"].dropna()
    ret_5 = frame["ret_5"].dropna()
    ret_20 = frame["ret_20"].dropna()
    top = ret_5.quantile(0.90)
    bottom = ret_5.quantile(0.10)
    advance_ratio = float((ret_1 > 0).mean())
    breadth_5 = float((ret_5 > 0).mean())
    median_ret_5 = float(ret_5.median())
    median_ret_20 = float(ret_20.median())
    limit_up = float((ret_1 >= 0.095).mean())
    limit_down = float((ret_1 <= -0.095).mean())
    weak_ratio = float((ret_5 <= -0.05).mean())
    volume_expansion = float(frame["volume_ratio"].median())

    breadth_component = float(_clip01((advance_ratio - 0.30) / 0.40))
    money_component = float(_clip01((median_ret_5 + 0.08) / 0.22))
    trend_component = float(_clip01((median_ret_20 + 0.18) / 0.48))
    limit_component = float(_clip01((limit_up - limit_down + 0.025) / 0.08))
    score = (
        0.30 * breadth_component
        + 0.25 * money_component
        + 0.25 * trend_component
        + 0.20 * limit_component
    )
    return {
        "sentiment_score": score,
        "advance_ratio": advance_ratio,
        "breadth_5": breadth_5,
        "median_ret_5": median_ret_5,
        "median_ret_20": median_ret_20,
        "limit_up_proxy": limit_up,
        "limit_down_proxy": limit_down,
        "weak_ratio": weak_ratio,
        "volume_expansion": volume_expansion,
        "top_decile_ret_5": float(top),
        "bottom_decile_ret_5": float(bottom),
    }


def classify_regime(sentiment: dict[str, float], previous_score: float | None, config: Config) -> str:
    score = sentiment["sentiment_score"]
    # A sudden breadth collapse is treated as weak even if the slower trend
    # component has not caught up yet.  This is an adaptive risk-control rule.
    breadth_shock = (
        previous_score is not None
        and score - previous_score <= -0.16
        and sentiment["advance_ratio"] < 0.40
    )
    if score >= config.strong_threshold and not breadth_shock:
        return REGIME_STRONG
    if score <= config.weak_threshold or breadth_shock:
        return REGIME_WEAK
    return REGIME_TRANSITION


def exposure_for(sentiment: dict[str, float], regime: str, previous_score: float | None) -> float:
    score = sentiment["sentiment_score"]
    if regime == REGIME_STRONG:
        return 1.0
    if regime == REGIME_WEAK:
        repair = previous_score is not None and score > previous_score + 0.08 and sentiment["advance_ratio"] > 0.45
        return 0.30 if repair else 0.10
    # Transition is a probing phase: enough exposure to participate, never a
    # full-size bet before the market confirms the direction.
    return float(np.clip(0.35 + (score - 0.40) * 1.25, 0.35, 0.80))


def select_names(
    frame: pd.DataFrame,
    strategy: str,
    regime: str,
    top_n: int,
    max_sector_names: int,
    previous: set[str],
    hold_buffer: int,
) -> list[str]:
    candidates = frame.loc[frame["signal_eligible"]].copy()
    if candidates.empty:
        return []
    if strategy == STRATEGY_LEADER:
        score = candidates["leader_score"]
    elif strategy == STRATEGY_REPAIR:
        score = candidates["panic_repair"]
    elif strategy == STRATEGY_BENCHMARK:
        # Benchmark is selected later as the full eligible universe.
        return candidates.index.tolist()
    elif regime == REGIME_STRONG:
        # Strong state: follow the market-selected relative leaders, but only
        # let a repair/pullback component break ties.  This is the systematic
        # form of "强势做强、买在分歧".
        score = (
            0.60 * candidates["r_ret_20"]
            + 0.25 * candidates["panic_repair"]
            + 0.15 * candidates["r_ret_1"]
        )
    elif regime == REGIME_WEAK:
        # Weak state: do not buy an unselective falling knife; require a
        # relative-strength floor and a positive repair signature.
        score = (
            0.45 * candidates["r_ret_20"]
            + 0.35 * candidates["panic_repair"]
            + 0.20 * candidates["r_ret_1"]
        )
    else:
        # Transition is the highest-uncertainty state: favour repair and use
        # momentum only as a confirmation rather than a chase signal.
        score = (
            0.70 * candidates["panic_repair"]
            + 0.20 * candidates["r_ret_20"]
            + 0.10 * candidates["r_ret_1"]
        )
    candidates = candidates.assign(selection_score=score).sort_values(
        ["selection_score", "leader_score"], ascending=False
    )
    rank = candidates["selection_score"].rank(method="first", ascending=False)
    sticky = candidates.loc[
        candidates.index.isin(previous)
        & (rank <= top_n + hold_buffer)
        & ~candidates["consensus_exhaustion"]
    ]
    ordered = pd.concat([sticky, candidates.drop(index=sticky.index)])
    selected: list[str] = []
    sector_counts: dict[str, int] = {}
    for instrument, row in ordered.iterrows():
        sector = str(row["industry_code"])
        if sector_counts.get(sector, 0) >= max_sector_names:
            continue
        selected.append(instrument)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected) >= top_n:
            break
    return selected


def target_weights(
    selected: list[str],
    exposure: float,
    frame: pd.DataFrame,
) -> dict[str, float]:
    if not selected or exposure <= 0:
        return {}
    # Equal stock weights keep the result auditable.  The selection layer, not
    # an opaque optimizer, carries the concentration / core-stock decision.
    names = [name for name in selected if name in frame.index]
    if not names:
        return {}
    weight = exposure / len(names)
    return {name: weight for name in names}


def execute_target(
    desired: dict[str, float],
    previous: dict[str, float],
    snapshot: pd.DataFrame,
) -> tuple[dict[str, float], int]:
    """Apply target orders at T+1 open, preserving positions blocked by limits."""

    actual: dict[str, float] = {}
    pending: dict[str, float] = {}
    blocked_changes = 0
    instruments = set(previous) | set(desired)
    for instrument in instruments:
        row = snapshot.loc[instrument] if instrument in snapshot.index else None
        # A name that leaves the point-in-time universe is liquidated from the
        # model ledger; otherwise a missing row would leave a ghost position
        # alive forever.  Only a known T+1 price-limit/suspension event blocks
        # an otherwise valid order.
        blocked = row is not None and bool(row["entry_blocked"])
        target = float(desired.get(instrument, 0.0))
        old = float(previous.get(instrument, 0.0))
        if blocked and not np.isclose(target, old):
            blocked_changes += 1
            if old > 1e-12:
                actual[instrument] = old
            continue
        if target <= 1e-12:
            continue
        else:
            pending[instrument] = target

    # If a sell is blocked, the cash that should have been released is not
    # available for new buys.  Scale only the executable orders so the model
    # never creates leverage merely because a limit order could not fill.
    target_exposure = sum(max(value, 0.0) for value in desired.values())
    fixed_exposure = sum(actual.values())
    pending_exposure = sum(pending.values())
    available = max(target_exposure - fixed_exposure, 0.0)
    scale = min(1.0, available / pending_exposure) if pending_exposure > 0 else 0.0
    for instrument, target in pending.items():
        filled = target * scale
        if filled > 1e-12:
            actual[instrument] = filled
    return actual, blocked_changes


def realised_period(
    weights: dict[str, float],
    previous: dict[str, float],
    snapshot: pd.DataFrame,
    config: Config,
) -> dict[str, float | int]:
    buy = sum(max(weight - previous.get(name, 0.0), 0.0) for name, weight in weights.items())
    sell = sum(max(previous.get(name, 0.0) - weights.get(name, 0.0), 0.0) for name in previous)
    cost = buy * config.open_cost + sell * config.close_cost
    gross = 0.0
    missing = 0
    for name, weight in weights.items():
        if name not in snapshot.index:
            missing += 1
            continue
        forward = float(snapshot.at[name, "next_open"] / snapshot.at[name, "entry_open"] - 1.0) if (
            np.isfinite(snapshot.at[name, "next_open"])
            and np.isfinite(snapshot.at[name, "entry_open"])
            and snapshot.at[name, "entry_open"] > 0
        ) else np.nan
        if not np.isfinite(forward):
            missing += 1
            continue
        gross += weight * forward
    net = (1.0 + gross) * (1.0 - cost) - 1.0
    return {
        "gross_return": gross,
        "cost": cost,
        "net_return": net,
        "buy_turnover": buy,
        "sell_turnover": sell,
        "missing_returns": missing,
        "realised_exposure": sum(weights.values()),
    }


def _period_summary(periods: pd.DataFrame, config: Config) -> pd.DataFrame:
    pivot = periods.pivot(index="signal_date", columns="strategy", values="net_return")
    if STRATEGY_BENCHMARK not in pivot.columns:
        raise ValueError("Benchmark column missing from periods")
    benchmark = pivot[STRATEGY_BENCHMARK]
    rng = np.random.default_rng(config.seed)
    rows: list[dict[str, Any]] = []
    for strategy in pivot.columns:
        returns = pivot[strategy].dropna()
        if returns.empty:
            continue
        aligned = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
        excess = (aligned.iloc[:, 0] - aligned.iloc[:, 1]).to_numpy()
        periods_per_year = 252.0 / config.rebalance_step
        annual_return = float((1.0 + returns).prod() ** (periods_per_year / len(returns)) - 1.0)
        annual_vol = float(returns.std(ddof=1) * np.sqrt(periods_per_year)) if len(returns) > 1 else np.nan
        arithmetic_annual = float(returns.mean() * periods_per_year)
        sharpe = arithmetic_annual / annual_vol if np.isfinite(annual_vol) and annual_vol > 0 else np.nan
        mdd = _max_drawdown(returns)
        positives = returns[returns > 0].sum()
        negatives = returns[returns < 0].sum()
        stats = periods.loc[periods["strategy"] == strategy]
        ci_low, ci_high = _bootstrap_mean_ci(excess, rng, config.bootstrap_samples)
        rows.append(
            {
                "strategy": strategy,
                "periods": int(len(returns)),
                "annual_return": annual_return,
                "annual_volatility": annual_vol,
                "sharpe": sharpe,
                "max_drawdown": mdd,
                "calmar": annual_return / abs(mdd) if mdd < 0 else np.nan,
                "win_rate": float((returns > 0).mean()),
                "profit_factor": float(positives / abs(negatives)) if negatives < 0 else np.nan,
                "mean_excess": float(np.mean(excess)) if len(excess) else np.nan,
                "excess_win_rate": float(np.mean(excess > 0)) if len(excess) else np.nan,
                "excess_ci_2.5": ci_low,
                "excess_ci_97.5": ci_high,
                "avg_exposure": float(stats["realised_exposure"].mean()),
                "avg_holdings": float(stats["n_holdings"].mean()),
                "mean_turnover": float(stats[["buy_turnover", "sell_turnover"]].sum(axis=1).mean()),
                "total_cost": float(stats["cost"].sum()),
                "blocked_change_rate": float(stats["blocked_changes"].sum() / max(stats["requested_changes"].sum(), 1)),
                "missing_return_count": int(stats["missing_returns"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("annual_return", ascending=False).reset_index(drop=True)


def _subperiod_summary(periods: pd.DataFrame, config: Config) -> pd.DataFrame:
    bins = [
        ("2015-2017", "2015-01-01", "2017-12-31"),
        ("2018-2020", "2018-01-01", "2020-12-31"),
        ("2021-2023", "2021-01-01", "2023-12-31"),
        ("2024-2026", "2024-01-01", "2026-12-31"),
    ]
    rows: list[dict[str, Any]] = []
    for label, start, end in bins:
        part = periods.loc[periods["signal_date"].between(start, end)]
        for strategy, group in part.groupby("strategy"):
            returns = group.sort_values("signal_date")["net_return"]
            if returns.empty:
                continue
            periods_per_year = 252.0 / config.rebalance_step
            annual = float((1.0 + returns).prod() ** (periods_per_year / len(returns)) - 1.0)
            rows.append(
                {
                    "subperiod": label,
                    "strategy": strategy,
                    "periods": int(len(returns)),
                    "annual_return": annual,
                    "max_drawdown": _max_drawdown(returns),
                    "win_rate": float((returns > 0).mean()),
                    "avg_exposure": float(group["realised_exposure"].mean()),
                }
            )
    return pd.DataFrame(rows)


def run_backtest(config: Config) -> dict[str, Any]:
    cal = calendar()
    dates = signal_dates(cal, config)
    date_positions = {date: int(cal.searchsorted(date)) for date in dates}
    universe = PointInTimeUniverse(config.market, dates)
    industries = IndustrySnapshots()
    store = RawQlibStore()
    auxiliary = AuxiliaryStore() if config.use_auxiliary else None
    previous_weights: dict[str, dict[str, float]] = {strategy: {} for strategy in STRATEGIES}
    previous_score: float | None = None
    period_rows: list[dict[str, Any]] = []
    sentiment_rows: list[dict[str, Any]] = []

    for number, date in enumerate(dates, 1):
        if number == 1 or number % 100 == 0 or number == len(dates):
            print(f"  [{number}/{len(dates)}] {date.date()} ({len(universe.at(number - 1))} members)", flush=True)
        snapshot = load_snapshot(
            date=date,
            position=date_positions[date],
            members=universe.at(number - 1),
            industry_map=industries.at(date),
            store=store,
            auxiliary=auxiliary,
            forward_sessions=config.rebalance_step,
        )
        frame = prepare_snapshot(snapshot, config)
        sentiment = market_sentiment(frame)
        regime = classify_regime(sentiment, previous_score, config)
        exposure = exposure_for(sentiment, regime, previous_score)
        sentiment_rows.append({"signal_date": date, "regime": regime, "exposure": exposure, **sentiment})

        selected = {
            STRATEGY_YJ_EP: select_names(
                frame, STRATEGY_YJ_EP, regime, config.top_n, config.max_sector_names,
                set(previous_weights[STRATEGY_YJ_EP]), config.hold_buffer,
            ),
            STRATEGY_LEADER: select_names(
                frame, STRATEGY_LEADER, regime, config.top_n, config.max_sector_names,
                set(previous_weights[STRATEGY_LEADER]), config.hold_buffer,
            ),
            STRATEGY_REPAIR: select_names(
                frame, STRATEGY_REPAIR, regime, config.top_n, config.max_sector_names,
                set(previous_weights[STRATEGY_REPAIR]), config.hold_buffer,
            ),
            STRATEGY_BENCHMARK: select_names(
                frame, STRATEGY_BENCHMARK, regime, config.top_n, config.max_sector_names,
                set(previous_weights[STRATEGY_BENCHMARK]), config.hold_buffer,
            ),
        }
        exposures = {
            STRATEGY_YJ_EP: exposure,
            STRATEGY_LEADER: exposure,
            STRATEGY_REPAIR: exposure,
            STRATEGY_BENCHMARK: 1.0,
        }
        for strategy in STRATEGIES:
            desired = target_weights(selected[strategy], exposures[strategy], frame)
            actual, blocked = execute_target(desired, previous_weights[strategy], snapshot)
            stats = realised_period(actual, previous_weights[strategy], snapshot, config)
            requested_changes = sum(
                not np.isclose(desired.get(name, 0.0), previous_weights[strategy].get(name, 0.0))
                for name in set(desired) | set(previous_weights[strategy])
            )
            period_rows.append(
                {
                    "signal_date": date,
                    "execution_date": pd.Timestamp(cal[date_positions[date] + 1]),
                    "strategy": strategy,
                    "regime": regime,
                    "sentiment_score": sentiment["sentiment_score"],
                    "target_exposure": exposures[strategy],
                    "n_holdings": len(actual),
                    "universe_size": len(frame),
                    "selected_names": len(selected[strategy]),
                    "blocked_changes": blocked,
                    "requested_changes": requested_changes,
                    **stats,
                }
            )
            previous_weights[strategy] = actual
        previous_score = sentiment["sentiment_score"]

    periods = pd.DataFrame(period_rows).sort_values(["signal_date", "strategy"]).reset_index(drop=True)
    sentiments = pd.DataFrame(sentiment_rows)
    summary = _period_summary(periods, config)
    subperiods = _subperiod_summary(periods, config)
    output_dir = OUTPUT_DIR / "yangjia_expectation_pressure" / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    periods.to_csv(output_dir / "period_returns.csv", index=False)
    sentiments.to_csv(output_dir / "sentiment_history.csv", index=False)
    summary.to_csv(output_dir / "summary.csv", index=False)
    subperiods.to_csv(output_dir / "subperiods.csv", index=False)

    regime_rows = []
    for (strategy, regime), group in periods.groupby(["strategy", "regime"]):
        regime_rows.append(
            {
                "strategy": strategy,
                "regime": regime,
                "periods": int(len(group)),
                "mean_net_return": float(group["net_return"].mean()),
                "win_rate": float((group["net_return"] > 0).mean()),
                "avg_exposure": float(group["realised_exposure"].mean()),
            }
        )
    regime_summary = pd.DataFrame(regime_rows)
    regime_summary.to_csv(output_dir / "regime_summary.csv", index=False)

    results = {
        "run": output_dir.name,
        "config": asdict(config),
        "data": {
            "provider_uri": str(QLIB_DATA_DIR),
            "qlib_calendar_start": str(cal[0].date()),
            "qlib_calendar_end": str(cal[-1].date()),
            "signal_start": str(dates[0].date()),
            "signal_end": str(dates[-1].date()),
            "point_in_time_universe": config.market,
            "industry_snapshot_count": len(industries.dates),
            "auxiliary_root": str(auxiliary.root) if auxiliary else None,
        },
        "method": {
            "name": "YJ-EP v3 (Yangjia Expectation-Pressure)",
            "philosophy": "情绪周期 + 主流板块宽度 + 核心股分歧/修复 + 动态仓位",
            "signal_timing": "T close signal -> T+1 open execution -> T+(rebalance_step+1) open exit",
            "market_state": "涨跌家数、5/20日收益中位数、涨跌停代理、量能扩张",
            "strong_state": "主流板块强度/宽度 + 板块内相对强势 + 趋势回撤",
            "weak_state": "5/20日超跌 + 当日收盘修复 + 量能/收盘位置确认",
            "transition_state": "龙头、预期差、修复信号混合",
            "v3_selection": "强势期以20日相对强度为主并用修复确认；过渡期以修复为主；弱势期用相对强度过滤下跌股后做修复",
            "sell_consensus_proxy": "极端短期上涨 + 高收盘位置 + 异常放量时不追且退出",
            "execution": "open-to-open, commissions included, blocked limit changes preserved",
            "future_data_policy": "ranking fields use T and earlier only; T+1/T+2 are execution outcomes",
        },
        "regime_distribution": sentiments["regime"].value_counts().to_dict(),
        "summary": summary.to_dict(orient="records"),
        "regime_summary": regime_summary.to_dict(orient="records"),
        "output_dir": str(output_dir),
    }
    (output_dir / "results.json").write_text(
        json.dumps(_json_safe(results), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[output] {output_dir}", flush=True)
    print(summary.to_string(index=False), flush=True)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YJ-EP 养家预期差/压力释放回测")
    parser.add_argument("--market", default=Config.market)
    parser.add_argument("--start", default=Config.start)
    parser.add_argument("--end", default=None)
    parser.add_argument("--rebalance-step", type=int, default=Config.rebalance_step)
    parser.add_argument("--top-n", type=int, default=Config.top_n)
    parser.add_argument("--max-sector-names", type=int, default=Config.max_sector_names)
    parser.add_argument("--hold-buffer", type=int, default=Config.hold_buffer)
    parser.add_argument("--bootstrap-samples", type=int, default=Config.bootstrap_samples)
    parser.add_argument("--no-auxiliary", action="store_true")
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    config = Config(
        market=args.market,
        start=args.start,
        end=args.end,
        rebalance_step=args.rebalance_step,
        top_n=args.top_n,
        max_sector_names=args.max_sector_names,
        hold_buffer=args.hold_buffer,
        bootstrap_samples=args.bootstrap_samples,
        use_auxiliary=not args.no_auxiliary,
    )
    print("=" * 72)
    print("  YJ-EP 养家预期差 / 压力释放策略回测")
    print("=" * 72)
    print(f"  market={config.market} start={config.start} end={config.end or 'latest Qlib date'}")
    print(f"  top_n={config.top_n} max_sector_names={config.max_sector_names} auxiliary={config.use_auxiliary}")
    return run_backtest(config)


if __name__ == "__main__":
    main()
