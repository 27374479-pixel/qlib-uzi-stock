"""Second-generation, point-in-time replay for five public short-term styles.

The first replay translated the five styles into one coarse score per style.
That is useful as a baseline, but it misses an important part of the public
material: each trader changes method with market emotion, observes a sector or
cohort rather than an isolated stock, and waits for a visible confirmation.

This module keeps the original loader and execution model, but adds:

* point-in-time industry/cohort synchronisation;
* prior-market ``money_making``/``fear``/``oversold`` state;
* separate setup modes for each style;
* explicit clock, board-stage, invalidation and confidence fields;
* out-of-sample-style stratified reports by mode, regime and time bucket.

It is still a research proxy.  Public quotations cannot reproduce private
watchlists, order queues, news interpretation or position management.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import five_experts_intraday_backtest as base
from config import OUTPUT_DIR, PROJECT_ROOT


INDUSTRY_DIR = PROJECT_ROOT / "data_lake" / "raw" / "baostock" / "industry_snapshots"
EVENT_DIR = PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "recent_events"
INDEX_DIR = PROJECT_ROOT / "data_lake" / "raw" / "baostock" / "index_daily"
EVENT_TYPES = ("limit_up", "previous_limit_up", "broken_board", "limit_down")


def _asof_industry_map(signal_date: pd.Timestamp, cache: dict[str, Any]) -> tuple[dict[str, str], str | None]:
    """Return the latest industry snapshot known *on or before* signal_date."""

    available = cache.setdefault(
        "available",
        sorted(
            (pd.to_datetime(path.stem, format="%Y%m%d", errors="coerce"), path)
            for path in INDUSTRY_DIR.glob("*.parquet")
            if not pd.isna(pd.to_datetime(path.stem, format="%Y%m%d", errors="coerce"))
        ),
    )
    eligible = [(date, path) for date, path in available if date.normalize() <= signal_date.normalize()]
    if not eligible:
        return {}, None
    snapshot_date, path = eligible[-1]
    key = str(snapshot_date.date())
    if key not in cache:
        try:
            frame = pd.read_parquet(path, columns=["instrument", "industry_code"])
        except Exception:
            frame = pd.DataFrame(columns=["instrument", "industry_code"])
        if not frame.empty:
            frame["instrument"] = frame["instrument"].astype(str).str.upper()
            frame["industry_code"] = frame["industry_code"].astype(str).replace({"nan": "UNKNOWN"})
            cache[key] = dict(zip(frame["instrument"], frame["industry_code"]))
        else:
            cache[key] = {}
    return cache[key], key


def load_event_history() -> pd.DataFrame:
    """Load the historical Eastmoney event pools without using fetch time.

    The event files are downloaded later than their ``pool_date`` in this
    project.  They are usable for replay only as an end-of-day observation of
    that pool date, and only on a later signal date.  ``knowledge_time`` is
    therefore deliberately not used as a feature timestamp.
    """

    rows: list[pd.DataFrame] = []
    for event_type in EVENT_TYPES:
        directory = EVENT_DIR / event_type
        for path in sorted(directory.glob("*.parquet")):
            try:
                frame = pd.read_parquet(path)
            except Exception:
                continue
            if frame.empty:
                continue
            frame = frame.copy()
            frame["event_type"] = event_type
            pool_values = frame["pool_date"] if "pool_date" in frame else pd.Series(path.stem, index=frame.index)
            frame["event_date"] = pd.to_datetime(
                pool_values, format="%Y%m%d", errors="coerce"
            ).dt.normalize()
            if "instrument" not in frame:
                continue
            frame["instrument"] = frame["instrument"].astype(str).str.upper()
            for column in ("board_days", "board_count", "em_hs", "em_zdp", "em_amount"):
                if column not in frame:
                    frame[column] = np.nan
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            if "em_hybk" not in frame:
                frame["em_hybk"] = ""
            frame["em_hybk"] = frame["em_hybk"].fillna("").astype(str)
            rows.append(
                frame[
                    [
                        "event_date", "event_type", "instrument", "board_days", "board_count",
                        "em_hs", "em_zdp", "em_amount", "em_hybk",
                    ]
                ]
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "event_date", "event_type", "instrument", "board_days", "board_count",
                "em_hs", "em_zdp", "em_amount", "em_hybk",
            ]
        )
    result = pd.concat(rows, ignore_index=True)
    result = result.dropna(subset=["event_date", "instrument"])
    return result.sort_values(["event_date", "instrument", "event_type"]).reset_index(drop=True)


def _asof_event_snapshot(
    signal_date: pd.Timestamp, history: pd.DataFrame, cache: dict[str, Any]
) -> tuple[pd.DataFrame, str | None, dict[str, int]]:
    """Return the last complete event pool strictly before ``signal_date``."""

    if history.empty:
        return pd.DataFrame(), None, {}
    if "em_hybk" not in history:
        history = history.copy()
        history["em_hybk"] = ""
    dates = cache.setdefault("event_dates", sorted(pd.Timestamp(x) for x in history["event_date"].unique()))
    eligible = [date for date in dates if date.normalize() < signal_date.normalize()]
    if not eligible:
        return pd.DataFrame(), None, {}
    source_date = eligible[-1]
    key = str(source_date.date())
    cached = cache.get(key)
    if cached is not None:
        return cached

    day = history.loc[history["event_date"] == source_date].copy()
    counts = {event_type: int((day["event_type"] == event_type).sum()) for event_type in EVENT_TYPES}
    board_themes = day.loc[
        day["event_type"].isin(["limit_up", "previous_limit_up"]) & day["em_hybk"].ne("")
    ]["em_hybk"]
    theme_counts = board_themes.value_counts()
    counts["theme_count"] = int(len(theme_counts))
    counts["theme_top_share"] = float(theme_counts.iloc[0] / board_themes.size) if not board_themes.empty else np.nan
    stock = pd.DataFrame(index=pd.Index(day["instrument"].unique(), name="instrument"))
    for event_type in EVENT_TYPES:
        subset = day.loc[day["event_type"] == event_type].set_index("instrument")
        flag = f"prior_event_{event_type}_stock"
        stock[flag] = 0.0
        if not subset.empty:
            stock.loc[subset.index, flag] = 1.0
    board_rows = day.loc[day["event_type"].isin(["limit_up", "previous_limit_up"])]
    if not board_rows.empty:
        board = board_rows.groupby("instrument", sort=False).agg(
            prior_event_board_days=("board_days", "max"),
            prior_event_board_count=("board_count", "max"),
            prior_event_turnover=("em_hs", "max"),
            prior_event_change=("em_zdp", "max"),
            prior_event_amount=("em_amount", "max"),
        )
        stock = stock.join(board, how="left")
        theme_by_stock = board_rows.loc[board_rows["em_hybk"].ne("")].groupby("instrument", sort=False)["em_hybk"].first()
        stock["prior_event_theme"] = theme_by_stock
    else:
        stock["prior_event_theme"] = ""
    for column in (
        "prior_event_board_days", "prior_event_board_count", "prior_event_turnover",
        "prior_event_change", "prior_event_amount",
    ):
        if column not in stock:
            stock[column] = np.nan
    if "prior_event_theme" not in stock:
        stock["prior_event_theme"] = ""
    stock["prior_event_theme"] = stock["prior_event_theme"].fillna("").astype(str)
    payload = stock.reset_index(), key, counts
    cache[key] = payload
    return payload


def load_index_daily_features() -> pd.DataFrame:
    """Build broad-index trend features from cached BaoStock daily bars."""

    rows: list[pd.DataFrame] = []
    for path in sorted(INDEX_DIR.glob("*.parquet")):
        try:
            frame = pd.read_parquet(path, columns=["date", "close"])
        except Exception:
            continue
        if frame.empty:
            continue
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["date", "close"]).copy()
        frame["instrument"] = path.stem.upper()
        rows.append(frame)
    if not rows:
        return pd.DataFrame()
    prices = pd.concat(rows, ignore_index=True).pivot_table(
        index="date", columns="instrument", values="close", aggfunc="last"
    ).sort_index()
    metrics = pd.DataFrame(index=prices.index)
    returns = {}
    for window in (1, 3, 5):
        returns[window] = prices.pct_change(window)
        metrics[f"index_ret{window}"] = returns[window].median(axis=1)
    metrics["index_positive_ratio"] = (returns[1] > 0).mean(axis=1)
    metrics["index_negative_ratio"] = (returns[1] < 0).mean(axis=1)
    metrics["index_available_count"] = prices.notna().sum(axis=1)
    return metrics.reset_index()


def _prior_index_asof(index_daily: pd.DataFrame, signal_date: pd.Timestamp) -> pd.Series:
    if index_daily.empty:
        return pd.Series(dtype=float)
    rows = index_daily.loc[index_daily["date"] < signal_date]
    if rows.empty:
        return pd.Series(dtype=float)
    return rows.sort_values("date").iloc[-1]


def build_prior_market_features(daily: pd.DataFrame) -> pd.DataFrame:
    """Build market state only from completed daily observations.

    The current-day state is computed from minute bars at each cutoff.  These
    rows provide the prior-day context needed for an oversold or transition
    decision without using the signal day's close.
    """

    if daily.empty:
        return pd.DataFrame()
    grouped = daily.groupby("date", sort=True)
    market = grouped.agg(
        market_median_ret=("ret1", "median"),
        market_mean_ret=("ret1", "mean"),
        market_n=("ret1", "count"),
        limit_up_count=("limit_locked", "sum"),
        touched_count=("limit_touched", "sum"),
    )
    market["market_breadth"] = grouped["ret1"].apply(lambda s: float((s > 0).mean() - (s < 0).mean()))
    market["market_up_ratio"] = grouped["ret1"].apply(lambda s: float((s > 0.03).mean()))
    market["market_down_ratio"] = grouped["ret1"].apply(lambda s: float((s < -0.03).mean()))
    broken = daily.assign(
        _broken_board=daily["limit_touched"] & ~daily["limit_locked"]
    ).groupby("date")[["_broken_board"]].sum()
    market["broken_board_count"] = broken["_broken_board"].astype(int)
    market["broken_ratio"] = market["broken_board_count"] / market["touched_count"].clip(lower=1)
    market["board_quality"] = market["limit_up_count"] / market["touched_count"].clip(lower=1)
    market = market.sort_index()
    for window in (3, 5):
        market[f"market_ret{window}"] = market["market_median_ret"].rolling(window, min_periods=window).sum()
        market[f"market_breadth{window}"] = market["market_breadth"].rolling(window, min_periods=window).mean()
        market[f"market_down_ratio{window}"] = market["market_down_ratio"].rolling(window, min_periods=window).mean()
    market["daily_fear"] = (
        (market["market_breadth"] < -0.18)
        | (market["market_down_ratio"] > 0.22)
        | ((market["broken_ratio"] > 0.65) & (market["board_quality"] < 0.35))
    )
    market["daily_money_making"] = (
        (market["market_breadth"] > 0.12)
        & (market["market_up_ratio"] > 0.10)
        & (market["market_down_ratio"] < 0.18)
        & (market["broken_ratio"] < 0.62)
    )
    return market.reset_index()


def build_prior_stock_features(daily: pd.DataFrame) -> pd.DataFrame:
    """Add ranges/streaks that are known as of the previous completed day."""

    frame = daily.sort_values(["instrument", "date"]).copy()
    grouped = frame.groupby("instrument", sort=False)
    frame["prior_high5"] = grouped["high"].transform(lambda s: s.shift(1).rolling(5, min_periods=3).max())
    frame["prior_low5"] = grouped["low"].transform(lambda s: s.shift(1).rolling(5, min_periods=3).min())
    frame["prior_high20"] = grouped["high"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).max())
    frame["prior_low20"] = grouped["low"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).min())
    frame["prior_ret3"] = grouped["close"].transform(lambda s: s.shift(1) / s.shift(4) - 1.0)
    frame["prior_ret1"] = grouped["ret1"].shift(1)
    frame["prior_down_streak3"] = grouped["ret1"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=3).apply(lambda x: float((x < 0).all()), raw=True)
    )
    frame["prior_up_streak3"] = grouped["ret1"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=3).apply(lambda x: float((x > 0).all()), raw=True)
    )
    return frame


def _prior_stock_asof(prior_daily: pd.DataFrame, signal_date: pd.Timestamp) -> pd.DataFrame:
    rows = prior_daily.loc[prior_daily["date"] < signal_date].sort_values(["instrument", "date"])
    if rows.empty:
        return pd.DataFrame()
    rows = rows.groupby("instrument", as_index=False).tail(1).set_index("instrument")
    columns = [
        "prior_high5", "prior_low5", "prior_high20", "prior_low20", "prior_ret3", "prior_ret1",
        "prior_down_streak3", "prior_up_streak3",
    ]
    return rows[[column for column in columns if column in rows]].copy()


def _prior_market_asof(market: pd.DataFrame, signal_date: pd.Timestamp) -> pd.Series:
    if market.empty:
        return pd.Series(dtype=float)
    rows = market.loc[market["date"] < signal_date]
    if rows.empty:
        return pd.Series(dtype=float)
    return rows.sort_values("date").iloc[-1]


def _market_phase(frame: pd.DataFrame) -> str:
    breadth = float(frame["market_breadth"].iloc[0])
    median = float(frame["market_median_intraday"].iloc[0])
    up_ratio = float(frame["market_up_ratio_2"].iloc[0])
    down_ratio = float(frame["market_down_ratio_2"].iloc[0])
    broken = float(frame["broken_ratio"].iloc[0])
    # The first version treated 20% of stocks below -2% as fear.  On a
    # five-minute as-of panel that is too sensitive: a healthy hot market can
    # still have many laggards.  Require breadth/median deterioration or a
    # combination of broad selling and poor board quality.
    if (breadth < -0.20) or (median < -0.012) or ((down_ratio > 0.35) and (broken > 0.68)):
        return "fear"
    if (breadth > 0.10) and (median > 0.002) and (up_ratio > 0.08) and (down_ratio < 0.30) and broken < 0.68:
        return "money_making"
    return "neutral"


def enrich_snapshot(
    snapshot: pd.DataFrame,
    signal_date: pd.Timestamp,
    prior_daily: pd.DataFrame,
    prior_market: pd.DataFrame,
    industry_cache: dict[str, Any],
    event_history: pd.DataFrame | None = None,
    event_cache: dict[str, Any] | None = None,
    index_daily: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Add all cohort and regime fields using information available at cutoff."""

    if snapshot.empty:
        return snapshot
    frame = snapshot.copy()
    industry_map, source_date = _asof_industry_map(signal_date, industry_cache)
    frame["industry_code"] = frame["instrument"].map(industry_map).fillna("UNKNOWN").astype(str)
    frame["industry_source_date"] = source_date
    event_cache = event_cache if event_cache is not None else {}
    event_stock, event_source_date, event_counts = _asof_event_snapshot(
        signal_date, event_history if event_history is not None else pd.DataFrame(), event_cache
    )
    frame["prior_event_source_date"] = event_source_date
    frame["prior_event_data_available"] = bool(event_source_date)
    for event_type in EVENT_TYPES:
        frame[f"prior_event_{event_type}_count_asof"] = float(event_counts.get(event_type, np.nan))
    frame["prior_event_theme_count_asof"] = float(event_counts.get("theme_count", np.nan))
    frame["prior_event_theme_top_share_asof"] = float(event_counts.get("theme_top_share", np.nan))
    if not event_stock.empty:
        frame = frame.join(event_stock.set_index("instrument"), on="instrument", how="left")
    for column in (
        "prior_event_limit_up_stock", "prior_event_previous_limit_up_stock",
        "prior_event_broken_board_stock", "prior_event_limit_down_stock",
    ):
        values = frame[column] if column in frame else pd.Series(0.0, index=frame.index)
        frame[column] = pd.to_numeric(values, errors="coerce").fillna(0.0)
    theme_values = frame["prior_event_theme"] if "prior_event_theme" in frame else pd.Series("", index=frame.index)
    frame["prior_event_theme"] = theme_values.fillna("").astype(str)
    for column in (
        "prior_event_board_days", "prior_event_board_count", "prior_event_turnover",
        "prior_event_change", "prior_event_amount",
    ):
        values = frame[column] if column in frame else pd.Series(np.nan, index=frame.index)
        frame[column] = pd.to_numeric(values, errors="coerce")
    prior_index = _prior_index_asof(index_daily if index_daily is not None else pd.DataFrame(), signal_date)
    frame["prior_index_data_available"] = bool(not prior_index.empty)
    for column in (
        "index_ret1", "index_ret3", "index_ret5", "index_positive_ratio", "index_negative_ratio",
        "index_available_count",
    ):
        frame[f"prior_{column}"] = prior_index.get(column, np.nan)
    frame["index_risk_contraction"] = (
        frame["prior_index_data_available"]
        & (
            (
                (frame["prior_index_ret3"] < -0.040)
                & (frame["prior_index_positive_ratio"] < 0.50)
            )
            | (
                (frame["prior_index_ret5"] < -0.045)
                & (frame["prior_index_positive_ratio"] < 0.50)
            )
        )
    )
    frame["index_supportive"] = (~frame["prior_index_data_available"]) | (~frame["index_risk_contraction"])
    prior_stock = _prior_stock_asof(prior_daily, signal_date)
    if not prior_stock.empty:
        frame = frame.join(prior_stock, on="instrument", how="left")
    else:
        for column in [
            "prior_high5", "prior_low5", "prior_high20", "prior_low20", "prior_ret3", "prior_ret1",
            "prior_down_streak3", "prior_up_streak3",
        ]:
            frame[column] = np.nan

    group = frame.groupby("industry_code", sort=False)
    group_stats = group.agg(
        group_n=("instrument", "size"),
        group_return_median=("intraday_return", "median"),
        group_return_mean=("intraday_return", "mean"),
        group_breadth=("intraday_return", lambda s: float((s > 0).mean() - (s < 0).mean())),
        group_up_ratio_2=("intraday_return", lambda s: float((s > 0.02).mean())),
        group_down_ratio_2=("intraday_return", lambda s: float((s < -0.02).mean())),
        group_late_median=("late_momentum_30m", "median"),
        group_prior10_median=("prior_ret10", "median"),
        group_amount_median=("amount_ratio_asof", "median"),
    )
    frame = frame.join(group_stats, on="industry_code")
    frame["group_intraday_rank"] = frame.groupby("industry_code")["intraday_return"].rank(pct=True)
    frame["group_prior10_rank"] = frame.groupby("industry_code")["prior_ret10"].rank(pct=True)
    frame["group_recovery_rank"] = frame.groupby("industry_code")["recovery_from_low"].rank(pct=True)
    frame["group_relative_return"] = frame["intraday_return"] - frame["group_return_median"]
    frame["group_attack"] = (
        (frame["group_n"] >= 3)
        & (frame["group_return_median"] > 0.005)
        & (frame["group_breadth"] > 0.20)
        & (frame["group_up_ratio_2"] > 0.20)
    )
    frame["group_stabilizing"] = (
        (frame["group_late_median"] > -0.001)
        & (frame["group_breadth"] > -0.10)
        & (frame["group_relative_return"] > -0.025)
    )

    returns = frame["intraday_return"].replace([np.inf, -np.inf], np.nan)
    late = frame["late_momentum_30m"].replace([np.inf, -np.inf], np.nan)
    frame["market_median_intraday"] = float(returns.median())
    frame["market_mean_intraday"] = float(returns.mean())
    frame["market_positive_ratio"] = float((returns > 0).mean())
    frame["market_negative_ratio"] = float((returns < 0).mean())
    frame["market_up_ratio_2"] = float((returns > 0.02).mean())
    frame["market_down_ratio_2"] = float((returns < -0.02).mean())
    frame["market_late_median"] = float(late.median())
    frame["market_late_positive_ratio"] = float((late > 0).mean())
    frame["market_phase"] = _market_phase(frame)

    prior = _prior_market_asof(prior_market, signal_date)
    for column in (
        "market_median_ret", "market_breadth", "market_up_ratio", "market_down_ratio", "market_ret3",
        "market_ret5", "market_breadth3", "market_breadth5", "market_down_ratio3", "market_down_ratio5",
        "daily_fear", "daily_money_making", "broken_ratio", "board_quality",
    ):
        frame[f"prior_{column}"] = prior.get(column, np.nan)
    frame["collective_oversold"] = (
        (frame["prior_market_ret3"] < -0.045)
        & (frame["prior_market_ret5"] < -0.060)
        & ((frame["prior_market_breadth3"] < -0.12) | (frame["prior_market_down_ratio3"] > 0.18))
        & (frame["prior_daily_fear"].fillna(False))
    )
    frame["collective_stabilizing"] = (
        (frame["market_late_median"] > 0.001)
        & (frame["market_positive_ratio"] >= frame["market_negative_ratio"] - 0.08)
        & (frame["market_median_intraday"] > -0.025)
    )
    frame["market_transition"] = (
        (frame["prior_daily_fear"].fillna(False))
        & (frame["market_phase"] != "fear")
        & frame["collective_stabilizing"]
    )
    frame["market_money_score"] = (
        0.45 * (frame["market_breadth"] + 1.0) / 2.0
        + 0.25 * frame["market_up_ratio_2"]
        + 0.20 * frame["market_late_positive_ratio"]
        - 0.20 * frame["market_down_ratio_2"]
    ).clip(0.0, 1.0)

    # A target/risk proxy is deliberately conservative: target is a prior
    # completed range high and risk is the observed pullback plus a 0.5% stop
    # buffer.  It is not the public quote's literal 3-5x promise.
    target = frame[["prior_high5", "prior_high20", "previous_close"]].max(axis=1, skipna=True)
    risk = ((frame["current_close"] - frame["current_low"]) / frame["current_close"]).clip(lower=0.005)
    frame["reward_space_proxy"] = (target / frame["current_close"] - 1.0).replace([np.inf, -np.inf], np.nan)
    frame["risk_space_proxy"] = risk.replace([np.inf, -np.inf], np.nan)
    frame["reward_risk_proxy"] = frame["reward_space_proxy"] / frame["risk_space_proxy"]

    # ``build_daily_features`` already names this prior-day rolling field
    # ``prior_locked_up5``; the as-of join prefixes it once more so the final
    # point-in-time column is ``prior_prior_locked_up5``.
    event_board_level = frame["prior_event_board_days"].fillna(0.0)
    daily_board_level = frame["prior_prior_locked_up5"].fillna(0.0)
    frame["board_level_proxy"] = (1.0 + pd.concat([daily_board_level, event_board_level], axis=1).max(axis=1)).clip(upper=6.0).astype(int)
    frame["board_stage"] = np.select(
        [
            frame["locked_upper"],
            frame["broken_upper"] & (frame["late_momentum_30m"] > 0),
            frame["gap_to_upper"].between(-0.025, -0.001),
            frame["gap_to_upper"].between(-0.060, -0.025),
        ],
        ["sealed", "broken_recover", "charging", "pre_charge"],
        default="ordinary",
    )
    frame["clock_bucket"] = np.select(
        [
            frame["cutoff"].isin(["09:45", "10:15"]),
            frame["cutoff"].isin(["14:00", "14:30"]),
            frame["cutoff"].isin(["10:45", "13:30"]),
        ],
        ["morning", "late", "midday"],
        default="other",
    )
    return frame


def _series(frame: pd.DataFrame, value: bool | pd.Series) -> pd.Series:
    if isinstance(value, pd.Series):
        return value.reindex(frame.index).fillna(False).astype(bool)
    return pd.Series(bool(value), index=frame.index)


def apply_style_rule_v2(
    frame: pd.DataFrame, style: str
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Return trigger, score, reason, mode and invalidation for one cutoff."""

    active = ~frame["locked_upper"]
    amount_ok = frame["amount_ratio_asof"].between(0.55, 3.8)
    group_size = frame["group_n"] >= 3
    group_support = frame["group_breadth"] > -0.10
    market_phase = frame["market_phase"]
    not_fear = market_phase != "fear"
    strong_market = market_phase == "money_making"
    prior_money_making = frame["prior_daily_money_making"].fillna(False).astype(bool)
    index_supportive = frame["index_supportive"].fillna(True).astype(bool)
    index_risk = frame["index_risk_contraction"].fillna(False).astype(bool)
    prior_board_evidence = (
        (frame["prior_event_limit_up_stock"] > 0)
        | (frame["prior_event_previous_limit_up_stock"] > 0)
        | (frame["prior_prior_limit_up5"].fillna(0) >= 1)
    )
    supportive_market = (
        strong_market
        | (
            (market_phase == "neutral")
            & (frame["market_median_intraday"] > 0.0010)
            & (frame["market_breadth"] > 0.05)
            & (frame["broken_ratio"] < 0.75)
        )
    )
    mode = pd.Series("no_trade", index=frame.index, dtype=object)
    reason = pd.Series("NO_TRADE", index=frame.index, dtype=object)
    invalidation = pd.Series("市场/板块/个股承接条件失效", index=frame.index, dtype=object)

    if style == "yangjia":
        low_absorption = (
            (market_phase == "money_making")
            & index_supportive
            & (frame["prior_ret10"] > 0.04)
            & ((frame["touched_upper"]) | (frame["prior_prior_limit_up5"] >= 1))
            & frame["from_high"].between(-0.075, -0.008)
            & (frame["late_momentum_30m"] > -0.003)
            & (frame["current_close"] >= frame["previous_close"] * 0.96)
            & (frame["group_relative_return"] > -0.015)
            & group_support
            & (frame["reward_risk_proxy"] >= 1.5)
        )
        oversold = (
            frame["collective_oversold"]
            & frame["collective_stabilizing"]
            & frame["market_transition"]
            & (frame["prior_down_streak3"] >= 1)
            & (frame["market_breadth"] > -0.02)
            & (frame["market_median_intraday"] > -0.005)
            & (frame["market_late_positive_ratio"] > 0.55)
            & (frame["recovery_from_low"] > 0.012)
            & (frame["late_momentum_30m"] > 0.001)
            & (frame["group_breadth"] > 0.0)
            & (frame["group_return_median"] > -0.005)
            & (frame["group_relative_return"] > -0.012)
            & (frame["reward_risk_proxy"] >= 1.2)
            & ((~index_risk) | frame["market_transition"])
        )
        trigger = active & amount_ok & group_size & (low_absorption | oversold)
        mode = pd.Series(np.select([low_absorption, oversold], ["money_making_low_absorption", "collective_oversold"], default="no_trade"), index=frame.index, dtype=object)
        reason = pd.Series(
            np.select(
                [low_absorption, oversold],
                [
                    "养家：赚钱效应下主线人气股分歧，承接/相对强度未坏，等待修复确认",
                    "养家：集体恐慌后的止跌修复，板块同步且风险收益重新对称",
                ],
                default="NO_TRADE",
            ),
            index=frame.index,
            dtype=object,
        )
        invalidation = pd.Series(
            np.where(
                oversold,
                "市场再次转入恐慌或板块/个股未能止跌",
                "跌破分歧低点、尾盘修复消失或板块同步转弱",
            ),
            index=frame.index,
            dtype=object,
        )
        score = (
            0.20 * frame["rank_prior10"]
            + 0.18 * frame["group_intraday_rank"]
            + 0.18 * frame["rank_recovery"]
            + 0.15 * frame["rank_late"]
            + 0.15 * (frame["reward_risk_proxy"] / 4.0).clip(0, 1)
            + 0.14 * frame["group_breadth"].add(1).div(2).clip(0, 1)
        )
    elif style == "zhiye":
        trend = (
            supportive_market
            & index_supportive
            & (frame["prior_ret10"] > 0.05)
            & (frame["prior_ret1"] < 0.085)
            & (frame["current_close"] / frame["previous_close"] - 1.0 > 0.012)
            & (frame["from_open"] > 0.004)
            & (frame["from_high"] > -0.035)
            & (frame["group_breadth"] > 0.08)
            & (frame["group_return_median"] > 0.002)
            & (frame["group_relative_return"] > -0.005)
            & (frame["rank_intraday"] >= 0.70)
        )
        pullback = (
            supportive_market
            & index_supportive
            & (frame["prior_ret10"] > 0.04)
            & (frame["prior_ret1"] < 0.08)
            & frame["from_high"].between(-0.055, -0.006)
            & (frame["late_momentum_30m"] > 0.001)
            & (frame["group_breadth"] > 0.05)
            & (frame["group_stabilizing"])
            & (frame["group_intraday_rank"] >= 0.60)
        )
        trigger = active & amount_ok & group_size & (trend | pullback)
        mode = pd.Series(np.select([trend, pullback], ["trend_continuation", "strong_pullback"], default="no_trade"), index=frame.index, dtype=object)
        reason = pd.Series(
            np.select(
                [trend, pullback],
                [
                    "职业炒手：非弱市主线趋势延续，放量/相对板块强度确认",
                    "职业炒手：强势板块回踩有承接，趋势未破坏后跟随",
                ],
                default="NO_TRADE",
            ),
            index=frame.index,
            dtype=object,
        )
        invalidation = pd.Series(
            "市场转弱、板块中位数转负或个股跌破回踩承接位", index=frame.index, dtype=object
        )
        score = (
            0.28 * frame["rank_intraday"]
            + 0.24 * frame["rank_prior10"]
            + 0.18 * frame["group_intraday_rank"]
            + 0.15 * frame["rank_late"]
            + 0.15 * _amount_quality_v2(frame["amount_ratio_asof"])
        )
    elif style == "asking":
        plan = (
            (frame["prior_ret10"] > 0.025)
            | (frame["prior_prior_limit_up5"] >= 1)
            | (frame["group_prior10_median"] > 0.02)
            | prior_board_evidence
        )
        trend_chase = (
            (frame["clock_bucket"] == "morning")
            & supportive_market
            & index_supportive
            & plan
            & frame["group_attack"]
            & (frame["current_close"] / frame["previous_close"] - 1.0 > 0.018)
            & (frame["from_open"] > 0.006)
            & (frame["amount_ratio_asof"] > 1.05)
            & (frame["group_intraday_rank"] >= 0.75)
            & (frame["gap_to_upper"] > -0.045)
        )
        leader_pullback = (
            (frame["clock_bucket"] == "late")
            & supportive_market
            & index_supportive
            & plan
            & (frame["prior_ret10"] > 0.035)
            & frame["from_high"].between(-0.075, -0.012)
            & (frame["late_momentum_30m"] > 0.0015)
            & (frame["recovery_from_low"] > 0.012)
            & (frame["group_breadth"] > 0.05)
            & (frame["group_intraday_rank"] >= 0.60)
        )
        oversold_rebound = (
            (frame["clock_bucket"] == "late")
            & frame["collective_oversold"]
            & frame["market_transition"]
            & frame["collective_stabilizing"]
            & (frame["market_breadth"] > -0.05)
            & (frame["market_median_intraday"] > -0.008)
            & (frame["recovery_from_low"] > 0.015)
            & (frame["late_momentum_30m"] > 0.002)
            & frame["group_stabilizing"]
            & (frame["group_recovery_rank"] >= 0.65)
            & ((~index_risk) | frame["market_transition"])
        )
        trigger = active & amount_ok & group_size & (trend_chase | leader_pullback | oversold_rebound)
        mode = pd.Series(
            np.select([trend_chase, leader_pullback, oversold_rebound], ["trend_chase", "leader_pullback", "oversold_rebound"], default="no_trade"),
            index=frame.index,
            dtype=object,
        )
        reason = pd.Series(
            np.select(
                [trend_chase, leader_pullback, oversold_rebound],
                [
                    "Asking：盘前计划中的热点龙头早盘放量转强，仍有可交易价格",
                    "Asking：计划内人气股尾盘回踩后再转强，节奏确认",
                    "Asking：弱市极端杀跌后的市场/板块/个股三层止跌反弹",
                ],
                default="NO_TRADE",
            ),
            index=frame.index,
            dtype=object,
        )
        invalidation = pd.Series(
            "计划主题失去强度、板块无扩散或下一根价格进入封死涨停/继续下杀", index=frame.index, dtype=object
        )
        score = (
            0.23 * frame["rank_late"]
            + 0.22 * frame["group_intraday_rank"]
            + 0.20 * frame["rank_recovery"]
            + 0.18 * frame["rank_prior10"]
            + 0.17 * _amount_quality_v2(frame["amount_ratio_asof"])
        )
    elif style == "zhao":
        theme_ready = (
            (frame["group_n"] >= 3)
            & (frame["group_breadth"] > 0.10)
            & (frame["group_up_ratio_2"] >= 0.20)
            & (frame["group_return_median"] > 0.005)
            & (frame["group_amount_median"] > 0.75)
        )
        new_theme = (
            supportive_market
            & index_supportive
            & theme_ready
            & (frame["group_prior10_median"] < 0.08)
            & (frame["current_close"] / frame["previous_close"] - 1.0 > 0.018)
            & (frame["group_intraday_rank"] >= 0.85)
            & (frame["rank_intraday"] >= 0.80)
        )
        old_theme_leader = (
            (supportive_market | (prior_money_making & frame["group_attack"]))
            & index_supportive
            & theme_ready
            & (prior_board_evidence | (frame["prior_ret10"] > 0.08))
            & (frame["group_prior10_median"] > 0.025)
            & (frame["prior_ret10"] > 0.045)
            & (frame["group_intraday_rank"] >= 0.90)
            & (frame["rank_intraday"] >= 0.85)
            & (frame["group_relative_return"] > 0.005)
        )
        leader_switch = (
            (supportive_market | (prior_money_making & frame["group_attack"]))
            & index_supportive
            & theme_ready
            & (prior_board_evidence | (frame["prior_ret10"] > 0.06))
            & (frame["group_intraday_rank"] >= 0.90)
            & (frame["group_prior10_rank"] <= 0.75)
            & (frame["rank_intraday"] >= 0.80)
            & (frame["amount_ratio_asof"] > 1.10)
        )
        trigger = active & amount_ok & (new_theme | old_theme_leader | leader_switch)
        mode = pd.Series(
            np.select([new_theme, old_theme_leader, leader_switch], ["new_theme_impulse", "old_theme_leader", "leader_switch"], default="no_trade"),
            index=frame.index,
            dtype=object,
        )
        reason = pd.Series(
            np.select(
                [new_theme, old_theme_leader, leader_switch],
                [
                    "赵老哥：新题材/新合力代理，板块扩散且最强者放量可交易",
                    "赵老哥：已有主线中最强龙头，板块同步而非单只跟风",
                    "赵老哥：板块内强弱切换，新的相对龙头完成确认",
                ],
                default="NO_TRADE",
            ),
            index=frame.index,
            dtype=object,
        )
        invalidation = pd.Series(
            "板块扩散停止、候选退居跟风或只剩无量封板", index=frame.index, dtype=object
        )
        score = (
            0.27 * frame["group_intraday_rank"]
            + 0.23 * frame["rank_intraday"]
            + 0.18 * frame["group_breadth"].add(1).div(2).clip(0, 1)
            + 0.17 * frame["rank_liquidity"]
            + 0.15 * _amount_quality_v2(frame["amount_ratio_asof"])
        )
    elif style == "lenghuchong":
        atmosphere = (
            index_supportive
            & (supportive_market | (prior_money_making & (market_phase == "neutral")))
            & (frame["prior_event_board_quality"].fillna(frame["board_quality"]) >= 0.40)
        )
        attack = frame["group_attack"] & (frame["group_intraday_rank"] >= 0.65)
        executable_stage = frame["board_stage"].isin(["pre_charge", "charging", "broken_recover"])
        high_conf = (
            atmosphere
            & attack
            & (frame["board_stage"].isin(["charging", "broken_recover"]))
            & (frame["board_level_proxy"] >= 2)
            & (frame["amount_ratio_asof"].between(0.8, 3.8))
        )
        medium_conf = (
            atmosphere
            & attack
            & executable_stage
            & (frame["board_level_proxy"] <= 2)
            & (frame["current_close"] / frame["previous_close"] - 1.0 > 0.025)
        )
        trigger = active & executable_stage & (high_conf | medium_conf)
        mode = pd.Series(
            np.select([high_conf, medium_conf], ["high_confidence_charge", "medium_confidence_charge"], default="no_trade"),
            index=frame.index,
            dtype=object,
        )
        reason = pd.Series(
            np.select(
                [high_conf, medium_conf],
                [
                    "冷狐冲：良好氛围/板块攻击/高板位，冲板过程中仍有可执行价格",
                    "冷狐冲：市场与板块同步，等待冲板换手和承接确认；不追封死板",
                ],
                default="NO_TRADE",
            ),
            index=frame.index,
            dtype=object,
        )
        invalidation = pd.Series(
            "炸板无回收、板块不跟、市场退潮或下一根K线封死导致不可成交", index=frame.index, dtype=object
        )
        score = (
            0.30 * (1.0 + frame["gap_to_upper"] / 0.025).clip(0, 1)
            + 0.22 * frame["group_intraday_rank"]
            + 0.20 * frame["rank_intraday"]
            + 0.15 * frame["rank_liquidity"]
            + 0.13 * _amount_quality_v2(frame["amount_ratio_asof"])
        )
    else:
        raise KeyError(style)

    score = score.replace([np.inf, -np.inf], np.nan)
    trigger = (trigger & score.notna()).fillna(False).astype(bool)
    score = score.fillna(-np.inf)
    return trigger, score, reason, mode, invalidation


def _amount_quality_v2(series: pd.Series) -> pd.Series:
    return (1.0 - np.log(series.clip(0.25, 8.0) / 1.15).abs() / np.log(8.0)).clip(0.0, 1.0)


def generate_signals_v2(
    snapshots: dict[tuple[pd.Timestamp, str], pd.DataFrame], top_n: int
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    signals: dict[str, pd.DataFrame] = {}
    count_rows: list[dict[str, Any]] = []
    for style in base.STYLE_NAMES:
        parts: list[pd.DataFrame] = []
        for (date, cutoff), frame in sorted(snapshots.items()):
            trigger, score, reason, mode, invalidation = apply_style_rule_v2(frame, style)
            count_rows.append(
                {
                    "style": style,
                    "date": str(date.date()),
                    "cutoff": cutoff,
                    "clock_bucket": str(frame["clock_bucket"].iloc[0]),
                    "market_phase": str(frame["market_phase"].iloc[0]),
                    "universe_n": int(len(frame)),
                    "market_breadth": float(frame["market_breadth"].iloc[0]),
                    "market_median_intraday": float(frame["market_median_intraday"].iloc[0]),
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
            part["mode"] = mode.loc[trigger]
            part["invalidation"] = invalidation.loc[trigger]
            part["signal_time"] = part["signal_datetime"]
            parts.append(part)
        if not parts:
            signals[style] = pd.DataFrame()
            continue
        # Keep the first executable trigger for each stock/day, then allocate
        # the day's limited slots to the strongest confirmed setups.  The old
        # chronological sort made an early weak probe displace a later,
        # higher-confidence confirmation, which is contrary to the
        # forecast -> trial -> confirmation -> add rhythm in the source text.
        candidates = pd.concat(parts, ignore_index=True).sort_values(
            ["signal_date", "instrument", "signal_datetime", "score"],
            ascending=[True, True, True, False],
        )
        candidates = candidates.drop_duplicates(["signal_date", "instrument"], keep="first")
        selected_parts = []
        for _, day in candidates.groupby("signal_date", sort=True):
            selected_parts.append(day.sort_values(["score", "signal_datetime"], ascending=[False, True]).head(top_n))
        selected = pd.concat(selected_parts, ignore_index=True) if selected_parts else pd.DataFrame()
        signals[style] = selected.sort_values(
            ["signal_date", "signal_datetime", "score"], ascending=[True, True, False]
        ).reset_index(drop=True)
    return signals, count_rows


def _stratified_summary(trades: pd.DataFrame, column: str) -> dict[str, Any]:
    if trades.empty or column not in trades:
        return {}
    result: dict[str, Any] = {}
    for key, group in trades.groupby(column, dropna=False, sort=True):
        label = "NA" if pd.isna(key) else str(key)
        result[label] = {
            "signals": int(len(group)),
            "filled": int(group["entry_filled"].sum()),
            "fill_rate": float(group["entry_filled"].mean()),
            "1d": base._summary(group.loc[group["entry_filled"], "return_1d"]),
            "2d": base._summary(group.loc[group["entry_filled"], "return_2d"]),
            "5d": base._summary(group.loc[group["entry_filled"], "return_5d"]),
        }
    return result


def _style_report_v2(trades: pd.DataFrame, full_dates: list[pd.Timestamp]) -> dict[str, Any]:
    report = base._style_report(trades, pd.DataFrame(), full_dates)
    report["by_mode"] = _stratified_summary(trades, "mode")
    report["by_market_phase"] = _stratified_summary(trades, "market_phase")
    report["by_clock_bucket"] = _stratified_summary(trades, "clock_bucket")
    report["by_board_stage"] = _stratified_summary(trades, "board_stage")
    if trades.empty:
        report["by_walk_forward_half"] = {}
    else:
        dates = sorted(pd.to_datetime(trades["signal_date"]).dt.normalize().dropna().unique())
        midpoint = dates[(len(dates) - 1) // 2]
        half = pd.to_datetime(trades["signal_date"]).dt.normalize().map(
            lambda value: "first_half" if value <= midpoint else "second_half"
        )
        report["by_walk_forward_half"] = _stratified_summary(
            trades.assign(_walk_forward_half=half), "_walk_forward_half"
        )
    report["invalidation_rules"] = (
        sorted({str(value) for value in trades["invalidation"].dropna()}) if not trades.empty else []
    )
    return report


def _json_safe(value: Any) -> Any:
    return base._json_safe(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Second-generation replay of five public short-term styles")
    parser.add_argument("--start", default=base.BacktestConfig.start)
    parser.add_argument("--end", default=base.BacktestConfig.end)
    parser.add_argument("--top-n", type=int, default=base.BacktestConfig.top_n)
    parser.add_argument("--min-history-days", type=int, default=base.BacktestConfig.min_history_days)
    parser.add_argument("--min-daily-bars", type=int, default=base.BacktestConfig.min_daily_bars)
    parser.add_argument("--signal-times", default=base.BacktestConfig.signal_times)
    parser.add_argument("--max-files", type=int, default=base.BacktestConfig.max_files)
    parser.add_argument(
        "--universe", choices=["cached", "csi800_start"], default=base.BacktestConfig.universe
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "five_experts_intraday_backtest_v2_latest.json")
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    config = base.BacktestConfig(
        start=args.start,
        end=args.end,
        top_n=max(1, args.top_n),
        min_history_days=max(3, args.min_history_days),
        min_daily_bars=max(20, args.min_daily_bars),
        signal_times=args.signal_times,
        max_files=max(0, args.max_files),
        universe=args.universe,
    )
    requested_start = base._date(config.start)
    requested_end = base._date(config.end) if config.end else pd.Timestamp("2100-01-01")
    universe_filter = base.csi800_members_asof(requested_start) if config.universe == "csi800_start" else None
    minutes = base.load_minutes(requested_start, requested_end, config.max_files, universe_filter)
    daily = base.build_daily_features(minutes, config.min_daily_bars)
    if daily.empty:
        raise ValueError("No completed daily rows")
    prior_daily = build_prior_stock_features(daily)
    prior_market = build_prior_market_features(daily)
    event_summary = base.load_event_summary()
    event_history = load_event_history()
    index_daily = load_index_daily_features()
    actual_last = pd.Timestamp(daily["date"].max())
    end = min(requested_end, actual_last)
    signal_times = [item.strip() for item in config.signal_times.split(",") if item.strip()]
    snapshots, signal_dates = base.build_snapshots(minutes, daily, requested_start, end, signal_times, event_summary)
    if len(signal_dates) <= config.min_history_days:
        raise ValueError(f"Too few completed signal dates: {len(signal_dates)}")
    industry_cache: dict[str, Any] = {}
    event_cache: dict[str, Any] = {}
    snapshots = {
        key: enrich_snapshot(
            value, key[0], prior_daily, prior_market, industry_cache, event_history, event_cache, index_daily
        )
        for key, value in snapshots.items()
    }
    trading_dates = sorted(pd.Timestamp(item) for item in daily["date"].drop_duplicates())
    usable_signal_dates = [
        item for item in signal_dates if item in trading_dates and trading_dates.index(item) + 5 < len(trading_dates)
    ]
    snapshots = {key: value for key, value in snapshots.items() if key[0] in usable_signal_dates}
    signals_by_style, signal_count_rows = generate_signals_v2(snapshots, config.top_n)
    reports: dict[str, Any] = {}
    trade_rows: list[dict[str, Any]] = []
    for style in base.STYLE_NAMES:
        signals = base.attach_outcomes(signals_by_style[style], minutes, trading_dates, config)
        reports[style] = _style_report_v2(signals, trading_dates)
        if not signals.empty:
            trade_rows.extend(signals.to_dict("records"))
    trades = pd.DataFrame(trade_rows)
    keep = {
        "style", "instrument", "signal_date", "cutoff", "signal_datetime", "score", "reason", "mode", "invalidation",
        "market_phase", "clock_bucket", "industry_code", "industry_source_date", "group_n", "group_breadth",
        "group_return_median", "group_relative_return", "group_attack", "board_level_proxy", "board_stage",
         "market_breadth", "market_median_intraday", "market_money_score", "collective_oversold", "collective_stabilizing",
         "reward_space_proxy", "risk_space_proxy", "reward_risk_proxy", "intraday_return", "from_high", "late_momentum_30m",
          "gap_to_upper", "prior_event_source_date", "prior_event_data_available", "prior_event_limit_up_stock",
          "prior_event_previous_limit_up_stock", "prior_event_broken_board_stock", "prior_event_limit_down_stock",
          "prior_event_board_days", "prior_event_board_count", "prior_event_turnover", "prior_event_theme",
          "prior_event_theme_count_asof", "prior_event_theme_top_share_asof", "prior_index_data_available",
         "prior_index_ret1", "prior_index_ret3", "prior_index_ret5", "prior_index_positive_ratio",
         "index_risk_contraction", "index_supportive", "entry_filled", "entry_reason",
         "entry_datetime", "entry_open", "exit_1d_filled", "exit_1d_reason",
        "exit_1d_date", "return_1d", "exit_2d_filled", "exit_2d_reason", "exit_2d_date", "return_2d",
        "exit_5d_filled", "exit_5d_reason", "exit_5d_date", "return_5d",
    }
    trade_output = []
    if not trades.empty:
        trade_output = [
            {_key: _json_safe(value) for _key, value in row.items() if _key in keep}
            for row in trades.to_dict("records")
        ]
    count_frame = pd.DataFrame(signal_count_rows)
    latest_market = []
    if not count_frame.empty:
        latest = count_frame.loc[count_frame["date"] == count_frame["date"].max()]
        latest_market = latest.drop_duplicates(["date", "cutoff"])[
            ["date", "cutoff", "clock_bucket", "market_phase", "universe_n", "market_breadth", "market_median_intraday", "limit_up_count", "broken_board_count"]
        ].to_dict("records")
    industry_known = int(sum((frame["industry_code"] != "UNKNOWN").sum() for frame in snapshots.values()))
    industry_total = int(sum(len(frame) for frame in snapshots.values()))
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": asdict(config),
        "version": "v2.2_regime_cohort_event_index_setup",
        "methodology": {
            "signal": "completed prior daily rows + current minute bars through cutoff + point-in-time industry cohort",
            "entry": "first five-minute bar strictly after signal timestamp, open price; locked up/down bars are unfilled",
            "exit": "T+1/T+2/T+5 first bar open with locked-down exit marked unfilled; T+1/T+2 are the primary short-term checks",
            "costs": f"open {config.open_cost:.4%}, close {config.close_cost:.4%}",
            "universe": (
                "fixed CSI800 membership at requested start; actual minute coverage must be checked"
                if config.universe == "csi800_start"
                else "cached event/available instruments; diagnostic universe, not a point-in-time market universe"
            ),
            "industry": "latest BaoStock CSRC snapshot dated on/before signal date; UNKNOWN is not treated as a theme",
            "event_history": "Eastmoney event pool uses pool_date as end-of-day knowledge; only prior pool dates are visible; event source coverage and decoded hybk themes are reported",
            "index_gate": "BaoStock SH000001/SZ399001/SZ399006/SH000300 prior-day trend; contraction is a style-specific veto except an explicit oversold transition",
            "selection": "first trigger per stock/day, then score-first top-N allocation; not chronological first-N allocation",
            "market_modes": "money_making, neutral, fear; collective_oversold requires prior multi-day market weakness plus current stabilization",
            "yangjia": "money-making low-absorption vs collective-oversold, relative strength, cohort synchronization, reward/risk proxy",
            "zhiye": "hard weak-market avoidance, trend continuation vs strong pullback, leader/cohort strength, no immediate oversized-win chase",
            "asking": "morning trend chase vs late leader pullback vs three-layer oversold rebound; midday is deliberately excluded",
            "zhao": "new-theme impulse vs old-theme leader vs leader switch; requires industry-cohort breadth and top-rank evidence",
            "lenghuchong": "atmosphere + cohort attack + pre-charge/charging/broken-recover board stage; sealed board is observation/unfilled",
            "no_lookahead": [
                "industry snapshot is selected only from dates <= signal date",
                "prior market and stock ranges use completed dates strictly before signal date",
                "current features use bars <= cutoff",
                "outcomes use only bars after the signal and are kept ex-post",
            ],
        },
        "data_quality": {
            "minute_rows": int(len(minutes)),
            "minute_instruments": int(minutes["instrument"].nunique()),
            "minute_start": str(minutes["datetime"].min()),
            "minute_end": str(minutes["datetime"].max()),
            "minute_source_rows": {str(k): int(v) for k, v in minutes["source"].value_counts(dropna=False).items()},
            "minute_source_instruments": {str(k): int(v) for k, v in minutes.groupby("source")["instrument"].nunique().items()},
            "universe_filter_instruments": int(len(universe_filter)) if universe_filter is not None else None,
            "completed_daily_dates": int(len(trading_dates)),
            "event_summary_dates": int(len(event_summary)) if not event_summary.empty else 0,
            "event_history_dates": int(event_history["event_date"].nunique()) if not event_history.empty else 0,
            "event_history_start": str(event_history["event_date"].min()) if not event_history.empty else None,
            "event_history_end": str(event_history["event_date"].max()) if not event_history.empty else None,
            "index_files": int(len(list(INDEX_DIR.glob("*.parquet")))) if not index_daily.empty else 0,
            "index_dates": int(len(index_daily)) if not index_daily.empty else 0,
            "industry_known_snapshot_rows": industry_known,
            "industry_snapshot_rows": industry_total,
            "industry_row_coverage": float(industry_known / industry_total) if industry_total else 0.0,
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
