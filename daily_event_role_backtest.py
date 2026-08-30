"""Causal daily validation of the event/theme/role interpretation of Uzi texts.

This is deliberately independent from ``long_uzi_state_backtest.py``.  The old
model is a useful industry-momentum baseline, but an industry return rank is not
the same thing as a new event, and the strongest return is not automatically a
tradable leader.

Daily bars cannot locate an intraday entry.  This module therefore answers the
narrower research question first: after a *completed* event-state transition,
does a core/survivor selected with information known at that close have useful
next-open-to-later-open expectancy?  A separate five-minute layer must validate
the actual divergence/reclaim trigger.
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


ROOT = Path(__file__).resolve().parent
DAILY_DIR = ROOT / "data_lake" / "raw" / "baostock" / "equity_daily"
INDUSTRY_DIR = ROOT / "data_lake" / "raw" / "baostock" / "industry_snapshots"
INSTRUMENT_DIR = ROOT / "qlib_data" / "cn_data" / "instruments"


@dataclass(frozen=True)
class Config:
    universe: str = "csi800"
    start: str = "2015-01-01"
    end: str = "2026-07-17"
    oos_start: str = "2023-01-01"
    round_trip_cost: float = 0.0018
    max_positions: int = 3
    output: str = "output/daily_event_role_csi800.json"
    trades_output: str = "output/daily_event_role_csi800_trades.parquet"


def _tick_round(values: pd.Series) -> pd.Series:
    """China price-limit tick rounding (half-up), vectorized to cents."""

    return np.floor(values.astype(float) * 100.0 + 0.5000001) / 100.0


def limit_ratio(instrument: str, dates: pd.Series) -> pd.Series:
    """Point-in-time regular A-share limit regime; ST rows are removed later."""

    code = instrument.upper()
    result = pd.Series(0.10, index=dates.index, dtype=float)
    if code.startswith("SH688"):
        result[:] = 0.20
    elif code.startswith("SZ30"):
        result.loc[pd.to_datetime(dates) >= pd.Timestamp("2020-08-24")] = 0.20
    return result


def load_membership(name: str) -> dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]]:
    path = INSTRUMENT_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(path)
    mapping: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.strip().split("\t")
            if len(parts) != 3:
                continue
            instrument, start, end = parts
            mapping.setdefault(instrument.upper(), []).append(
                (pd.Timestamp(start), pd.Timestamp(end))
            )
    return mapping


def _membership_mask(
    dates: pd.Series, intervals: list[tuple[pd.Timestamp, pd.Timestamp]]
) -> pd.Series:
    mask = pd.Series(False, index=dates.index)
    for start, end in intervals:
        mask |= dates.between(start, end)
    return mask


def load_industry_mapping() -> dict[str, tuple[np.ndarray, np.ndarray]]:
    parts: list[pd.DataFrame] = []
    for path in sorted(INDUSTRY_DIR.glob("*.parquet")):
        try:
            item = pd.read_parquet(
                path, columns=["snapshot_date", "instrument", "industry_code"]
            )
        except Exception:
            continue
        if not item.empty:
            parts.append(item)
    if not parts:
        return {}
    frame = pd.concat(parts, ignore_index=True)
    frame["snapshot_date"] = pd.to_datetime(frame["snapshot_date"]).dt.normalize()
    frame["instrument"] = frame["instrument"].astype(str).str.upper()
    frame["industry_code"] = frame["industry_code"].fillna("UNKNOWN").astype(str)
    frame = frame.drop_duplicates(["instrument", "snapshot_date"], keep="last")
    result: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for instrument, group in frame.groupby("instrument", sort=False):
        group = group.sort_values("snapshot_date")
        result[instrument] = (
            group["snapshot_date"].to_numpy(dtype="datetime64[ns]"),
            group["industry_code"].to_numpy(dtype=str),
        )
    return result


def _industry_series(
    instrument: str,
    dates: pd.Series,
    mapping: dict[str, tuple[np.ndarray, np.ndarray]],
) -> np.ndarray:
    item = mapping.get(instrument)
    if item is None:
        return np.full(len(dates), "UNKNOWN", dtype=object)
    snapshots, codes = item
    positions = np.searchsorted(
        snapshots, dates.to_numpy(dtype="datetime64[ns]"), side="right"
    ) - 1
    valid = positions >= 0
    result = np.full(len(dates), "UNKNOWN", dtype=object)
    result[valid] = codes[positions[valid]]
    return result


def _prepare_stock(
    path: Path,
    intervals: list[tuple[pd.Timestamp, pd.Timestamp]],
    industries: dict[str, tuple[np.ndarray, np.ndarray]],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    columns = [
        "instrument", "date", "open", "high", "low", "close", "preclose",
        "amount", "turnover_rate_pct", "trade_status", "is_st",
        "float_market_cap_est",
    ]
    frame = pd.read_parquet(path, columns=columns)
    if frame.empty:
        return frame
    instrument = str(frame["instrument"].iloc[0]).upper()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.loc[
        frame["date"].between(start - pd.Timedelta(days=60), end)
        & _membership_mask(frame["date"], intervals)
    ].copy()
    if frame.empty:
        return frame
    frame = frame.sort_values("date").reset_index(drop=True)
    numeric = [
        "open", "high", "low", "close", "preclose", "amount",
        "turnover_rate_pct", "float_market_cap_est", "trade_status", "is_st",
    ]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    frame = frame.loc[
        (frame["trade_status"] == 1)
        & (frame["is_st"] == 0)
        & (frame["preclose"] > 0)
        & (frame["close"] > 0)
    ].copy()
    if frame.empty:
        return frame
    frame["instrument"] = instrument
    frame["industry_code"] = _industry_series(instrument, frame["date"], industries)
    frame["limit_ratio"] = limit_ratio(instrument, frame["date"])
    frame["upper_limit"] = _tick_round(frame["preclose"] * (1 + frame["limit_ratio"]))
    frame["lower_limit"] = _tick_round(frame["preclose"] * (1 - frame["limit_ratio"]))
    tolerance = 0.011
    frame["touch_up"] = frame["high"] >= frame["upper_limit"] - tolerance
    frame["seal_up"] = frame["close"] >= frame["upper_limit"] - tolerance
    frame["one_word"] = frame["seal_up"] & (frame["low"] >= frame["upper_limit"] - tolerance)
    frame["broken_up"] = frame["touch_up"] & ~frame["seal_up"]
    frame["limit_down_close"] = frame["close"] <= frame["lower_limit"] + tolerance
    frame["ret1"] = frame["close"] / frame["preclose"] - 1
    frame["gap"] = frame["open"] / frame["preclose"] - 1
    frame["amount_base5"] = frame["amount"].shift(1).rolling(5, min_periods=3).mean()
    frame["amount_accel"] = frame["amount"] / frame["amount_base5"].replace(0, np.nan)
    frame["prior_seal5"] = frame["seal_up"].shift(1).rolling(5, min_periods=2).sum()
    frame["prior_touch20"] = frame["touch_up"].shift(1).rolling(20, min_periods=10).sum()
    frame["ret5"] = frame["close"] / frame["close"].shift(5) - 1
    frame["vol10"] = frame["ret1"].rolling(10, min_periods=7).std()
    # Consecutive sealed boards, known at each close.
    groups = (~frame["seal_up"]).cumsum()
    frame["board_height"] = frame["seal_up"].groupby(groups).cumsum().astype(int)
    frame["first_board"] = frame["seal_up"] & frame["prior_seal5"].fillna(0).eq(0)
    # Remove listing micro-history where IPO limit rules and missing pre-history
    # make the ordinary price-limit inference unreliable.
    frame["history_n"] = np.arange(len(frame)) + 1
    frame = frame.loc[(frame["history_n"] >= 20) & frame["date"].between(start, end)]
    return frame


def load_panel(config: Config) -> tuple[pd.DataFrame, dict[str, Any]]:
    membership = load_membership(config.universe)
    industries = load_industry_mapping()
    start, end = pd.Timestamp(config.start), pd.Timestamp(config.end)
    parts: list[pd.DataFrame] = []
    missing = 0
    for number, (instrument, intervals) in enumerate(sorted(membership.items()), 1):
        path = DAILY_DIR / f"{instrument}.parquet"
        if not path.exists():
            missing += 1
            continue
        item = _prepare_stock(path, intervals, industries, start, end)
        if not item.empty:
            parts.append(item)
        if number % 500 == 0:
            print(f"loaded {number}/{len(membership)} membership instruments", flush=True)
    if not parts:
        raise RuntimeError("no daily rows loaded")
    panel = pd.concat(parts, ignore_index=True).sort_values(["date", "instrument"])
    metadata = {
        "membership_instruments": len(membership),
        "loaded_instruments": int(panel["instrument"].nunique()),
        "missing_daily_files": missing,
        "rows": len(panel),
        "industry_known_ratio": float(panel["industry_code"].ne("UNKNOWN").mean()),
        "actual_start": str(panel["date"].min().date()),
        "actual_end": str(panel["date"].max().date()),
    }
    return panel.reset_index(drop=True), metadata


def build_market_state(panel: pd.DataFrame) -> pd.DataFrame:
    grouped = panel.groupby("date", sort=True)
    market = grouped.agg(
        universe_n=("instrument", "nunique"),
        breadth=("ret1", lambda x: float((x > 0).mean() - (x < 0).mean())),
        median_return=("ret1", "median"),
        touch_count=("touch_up", "sum"),
        seal_count=("seal_up", "sum"),
        down_count=("limit_down_close", "sum"),
    ).reset_index()
    market["broken_ratio"] = (market["touch_count"] - market["seal_count"]) / market[
        "touch_count"
    ].clip(lower=1)
    market["money_effect"] = panel.loc[panel["prior_seal5"].fillna(0) > 0].groupby("date")[
        "ret1"
    ].mean().reindex(market["date"]).to_numpy()
    market["money_effect"] = market["money_effect"].fillna(0)
    market["breadth5"] = market["breadth"].rolling(5, min_periods=3).mean()
    market["weak_market"] = (
        (market["breadth5"] < -0.12)
        | (market["money_effect"].rolling(3, min_periods=2).mean() < -0.012)
        | ((market["broken_ratio"] > 0.60) & (market["breadth"] < 0))
    )
    return market


def build_theme_state(panel: pd.DataFrame) -> pd.DataFrame:
    known = panel.loc[panel["industry_code"].ne("UNKNOWN")].copy()
    keys = ["date", "industry_code"]
    theme = known.groupby(keys, sort=True).agg(
        cohort_n=("instrument", "nunique"),
        cohort_return=("ret1", "mean"),
        positive_n=("ret1", lambda x: int((x > 0).sum())),
        first_board_n=("first_board", "sum"),
        touch_n=("touch_up", "sum"),
        seal_n=("seal_up", "sum"),
        broken_n=("broken_up", "sum"),
        max_board=("board_height", "max"),
        amount_accel=("amount_accel", "median"),
    ).reset_index()
    theme["broken_ratio"] = theme["broken_n"] / theme["touch_n"].clip(lower=1)
    theme["positive_ratio"] = theme["positive_n"] / theme["cohort_n"].clip(lower=1)
    theme = theme.sort_values(["industry_code", "date"])
    by_theme = theme.groupby("industry_code", sort=False)
    theme["prior_event20"] = by_theme["first_board_n"].transform(
        lambda x: x.shift(1).rolling(20, min_periods=5).sum()
    )
    theme["prev_first_board_n"] = by_theme["first_board_n"].shift(1)
    theme["prev_seal_n"] = by_theme["seal_n"].shift(1)
    theme["prev_max_board"] = by_theme["max_board"].shift(1)
    theme["prev_broken_ratio"] = by_theme["broken_ratio"].shift(1)
    theme["prior3_seal_max"] = by_theme["seal_n"].transform(
        lambda x: x.shift(1).rolling(3, min_periods=1).max()
    )
    theme["prior3_broken_max"] = by_theme["broken_ratio"].transform(
        lambda x: x.shift(1).rolling(3, min_periods=1).max()
    )
    # Stage names encode chronology.  They are intentionally coarse and use
    # completed closes only; no future maximum or ex-post theme labeling.
    theme["emergence"] = (
        (theme["first_board_n"] >= 2)
        & (theme["prior_event20"].fillna(0) <= 3)
        & (theme["positive_ratio"] >= 0.52)
    )
    theme["confirmation"] = (
        (theme["prev_first_board_n"] >= 2)
        & (theme["seal_n"] >= 1)
        & (theme["positive_ratio"] >= 0.50)
    )
    theme["climax"] = (
        (theme["seal_n"] >= 4)
        & (theme["broken_ratio"] <= 0.25)
        & (theme["positive_ratio"] >= 0.62)
    )
    theme["divergence"] = (
        (theme["prior3_seal_max"] >= 2)
        & ((theme["broken_ratio"] >= 0.50) | (theme["cohort_return"] <= -0.01))
    )
    theme["repair"] = (
        (theme["prior3_broken_max"] >= 0.50)
        & (theme["seal_n"] >= 2)
        & (theme["broken_ratio"] <= 0.40)
        & (theme["positive_ratio"] >= 0.55)
    )
    return theme


def add_roles(panel: pd.DataFrame, theme: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    frame = panel.merge(theme, on=["date", "industry_code"], how="left", suffixes=("", "_theme"))
    frame = frame.merge(market, on="date", how="left", suffixes=("", "_market"))
    keys = ["date", "industry_code"]
    # Percentile ranks avoid absolute-size hindsight and express relative role.
    frame["ret_rank"] = frame.groupby(keys)["ret1"].rank(pct=True)
    frame["amount_rank"] = frame.groupby(keys)["amount"].rank(pct=True)
    frame["turnover_rank"] = frame.groupby(keys)["turnover_rate_pct"].rank(pct=True)
    frame["float_cap_rank"] = frame.groupby(keys)["float_market_cap_est"].rank(pct=True)
    frame["role_score"] = (
        2.2 * frame["seal_up"].astype(float)
        + 0.7 * frame["touch_up"].astype(float)
        + 0.9 * frame["board_height"].clip(upper=3)
        + 0.8 * frame["ret_rank"].fillna(0.5)
        + 0.6 * frame["amount_rank"].fillna(0.5)
        + 0.4 * frame["turnover_rank"].fillna(0.5)
        - 0.35 * frame["float_cap_rank"].fillna(0.5)
        - 1.0 * frame["one_word"].astype(float)
    )
    frame["role_rank"] = frame.groupby(keys)["role_score"].rank(
        method="first", ascending=False
    )
    frame["core"] = (frame["role_rank"] <= 2) & (frame["touch_up"] | (frame["ret_rank"] >= 0.85))
    return frame


def make_signals(frame: pd.DataFrame) -> pd.DataFrame:
    # Confirmation: only the prior event cohort can be the core; new same-day
    # followers are deliberately excluded.  Entry still waits until next open.
    confirm = (
        frame["confirmation"].fillna(False)
        & frame["core"]
        & (frame["prior_seal5"].fillna(0) > 0)
        & ~frame["one_word"]
        & ~frame["weak_market"].fillna(True)
    )
    # Divergence survivor: a previously active core remains in the top part of
    # its cohort while the theme washes out.  This is the daily precursor to an
    # intraday divergence/reclaim entry, not a blind purchase at today's close.
    survivor = (
        frame["divergence"].fillna(False)
        & (frame["prior_seal5"].fillna(0) > 0)
        & (frame["ret_rank"] >= 0.75)
        & (frame["ret1"] >= -0.045)
        & (frame["ret1"] <= 0.065)
        & (frame["turnover_rate_pct"].between(1.0, 25.0))
    )
    repair = (
        frame["repair"].fillna(False)
        & frame["core"]
        & (frame["prior_touch20"].fillna(0) > 0)
        & ~frame["one_word"]
        & ~frame["weak_market"].fillna(True)
    )
    setup = np.select(
        [survivor, repair, confirm],
        ["divergence_survivor", "repair_core", "confirmation_core"],
        default="",
    )
    signals = frame.loc[setup != ""].copy()
    signals["setup"] = setup[setup != ""]
    # Demand versus supply proxy from the books: participation acceleration and
    # cohort breadth are demand; very large float and excessive turnover are
    # supply/churn.  It ranks candidates, it does not manufacture eligibility.
    signals["demand_supply_score"] = (
        np.log1p(signals["amount_accel"].clip(lower=0, upper=10)).fillna(0)
        + 0.8 * signals["positive_ratio"].fillna(0)
        + 0.5 * signals["role_score"].fillna(0)
        - 0.45 * np.log1p(signals["float_market_cap_est"] / 1e9).fillna(0)
        - 0.025 * signals["turnover_rate_pct"].clip(lower=0).fillna(0)
    )
    signals = signals.sort_values(
        ["date", "demand_supply_score"], ascending=[True, False]
    )
    signals["daily_rank"] = signals.groupby("date").cumcount() + 1
    return signals


def attach_outcomes(signals: pd.DataFrame, panel: pd.DataFrame, cost: float) -> pd.DataFrame:
    price = panel[["instrument", "date", "open", "low", "upper_limit", "lower_limit"]].copy()
    price = price.sort_values(["instrument", "date"])
    by_stock = {name: group.reset_index(drop=True) for name, group in price.groupby("instrument")}
    rows: list[dict[str, Any]] = []
    for record in signals.to_dict("records"):
        history = by_stock.get(record["instrument"])
        if history is None:
            continue
        positions = history.index[history["date"].eq(record["date"])]
        if len(positions) != 1:
            continue
        pos = int(positions[0])
        if pos + 1 >= len(history):
            continue
        entry = history.iloc[pos + 1]
        # If the next session never trades below its upper limit, the order is
        # unfilled.  Daily data cannot prove an opening-only lock more finely.
        entry_locked = bool(
            entry["open"] >= entry["upper_limit"] - 0.011
            and entry["low"] >= entry["upper_limit"] - 0.011
        )
        record["entry_date"] = entry["date"]
        record["entry_price"] = float(entry["open"])
        record["entry_filled"] = not entry_locked
        if entry_locked:
            rows.append(record)
            continue
        for horizon in (1, 2, 3, 5):
            exit_pos = pos + 1 + horizon
            if exit_pos >= len(history):
                continue
            exit_row = history.iloc[exit_pos]
            record[f"exit_{horizon}d_date"] = exit_row["date"]
            record[f"return_{horizon}d"] = float(exit_row["open"] / entry["open"] - 1 - cost)
        rows.append(record)
    return pd.DataFrame(rows)


def _event_metrics(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return {"n": 0}
    downside = values.loc[values < 0]
    return {
        "n": int(len(values)),
        "mean": float(values.mean()),
        "median": float(values.median()),
        "win_rate": float((values > 0).mean()),
        "payoff": float(values.loc[values > 0].mean() / abs(downside.mean()))
        if (values > 0).any() and not downside.empty else None,
        "p05": float(values.quantile(0.05)),
        "p95": float(values.quantile(0.95)),
    }


def portfolio_metrics(trades: pd.DataFrame, config: Config, horizon: int = 2) -> dict[str, Any]:
    column = f"return_{horizon}d"
    selected = trades.loc[
        trades["entry_filled"].fillna(False)
        & trades[column].notna()
        & (trades["daily_rank"] <= config.max_positions)
    ].copy()
    if selected.empty:
        return {"n": 0}
    daily = selected.groupby("entry_date")[column].mean().sort_index()
    # Capital is split across independent horizon buckets to avoid claiming the
    # same cash is fully invested in overlapping trades.
    bucket_return = daily / horizon
    equity = (1 + bucket_return).cumprod()
    years = max((daily.index.max() - daily.index.min()).days / 365.25, 1 / 252)
    total = float(equity.iloc[-1] - 1)
    cagr = float(equity.iloc[-1] ** (1 / years) - 1)
    drawdown = equity / equity.cummax() - 1
    volatility = float(bucket_return.std(ddof=1) * math.sqrt(252)) if len(daily) > 1 else None
    return {
        "n": int(len(selected)),
        "active_entry_days": int(len(daily)),
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": float(drawdown.min()),
        "annualized_volatility": volatility,
        "sharpe_zero_rf": float(cagr / volatility) if volatility and volatility > 0 else None,
    }


def summarize(trades: pd.DataFrame, config: Config, metadata: dict[str, Any]) -> dict[str, Any]:
    filled = trades.loc[trades["entry_filled"].fillna(False)].copy()
    split = pd.Timestamp(config.oos_start)
    report: dict[str, Any] = {
        "config": asdict(config),
        "data": metadata,
        "signals": int(len(trades)),
        "filled": int(len(filled)),
        "all": {},
        "development": {},
        "oos": {},
        "by_setup_oos": {},
        "portfolio_2d": portfolio_metrics(filled, config, 2),
        "portfolio_2d_oos": portfolio_metrics(filled.loc[filled["date"] >= split], config, 2),
        "limitations": [
            "CSRC industry is a point-in-time theme proxy, not the true news concept board.",
            "Daily bars validate state expectancy only; they cannot validate an intraday reclaim price.",
            "Index membership and available BaoStock files constrain historical coverage.",
            "No parameter search is performed in this script; thresholds are declared before OOS review.",
        ],
    }
    for horizon in (1, 2, 3, 5):
        col = f"return_{horizon}d"
        report["all"][col] = _event_metrics(filled, col)
        report["development"][col] = _event_metrics(filled.loc[filled["date"] < split], col)
        report["oos"][col] = _event_metrics(filled.loc[filled["date"] >= split], col)
    for setup, group in filled.loc[filled["date"] >= split].groupby("setup"):
        report["by_setup_oos"][setup] = {
            f"return_{h}d": _event_metrics(group, f"return_{h}d") for h in (1, 2, 3, 5)
        }
    return report


def run(config: Config) -> dict[str, Any]:
    panel, metadata = load_panel(config)
    market = build_market_state(panel)
    theme = build_theme_state(panel)
    enriched = add_roles(panel, theme, market)
    signals = make_signals(enriched)
    trades = attach_outcomes(signals, panel, config.round_trip_cost)
    report = summarize(trades, config, metadata)
    output = ROOT / config.output
    trades_output = ROOT / config.trades_output
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
    parser.add_argument("--output", default=Config.output)
    parser.add_argument("--trades-output", default=Config.trades_output)
    args = parser.parse_args()
    return Config(**vars(args))


if __name__ == "__main__":
    run(parse_args())
