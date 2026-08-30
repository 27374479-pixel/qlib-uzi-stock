"""Leakage-safe backtest for the 14:00 intraday candidate selector.

Signal construction is intentionally split across two clocks:

* T-1 close: create a broad candidate set from daily Qlib data;
* T 14:00: rank only with five-minute bars whose timestamp is <= 14:00;
* T 14:45 bar open: conservative executable entry after a 40-minute UZI window;
* T+1 / T+5 first bar open: evaluate outcomes after explicit costs.

Historical UZI qualitative reports are not replayed because the repository has
no as-of archive of news, filings and UZI judgments.  This script evaluates the
candidate-selection layer only and says so in its output.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import akshare as ak
import numpy as np
import pandas as pd

from candidate_funnel import FunnelConfig, get_calendar, init_qlib, load_factor_panel, select_candidates
from config import OUTPUT_DIR, PROJECT_ROOT


MINUTE_CACHE_DIR = PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "equity_5min"


@dataclass(frozen=True)
class BacktestConfig:
    days: int = 8
    base_top_n: int = 30
    final_top_n: int = 8
    signal_time: str = "14:00"
    decision_cutoff: str = "14:40"
    entry_bar_time: str = "14:45"
    min_intraday_return: float = -0.03
    max_intraday_return: float = 0.07
    min_from_open: float = -0.01
    min_from_high: float = -0.04
    min_amount_to_signal: float = 50_000_000.0
    min_amount_ratio: float = 0.50
    max_amount_ratio: float = 4.00
    open_cost: float = 0.0003
    close_cost: float = 0.0013
    workers: int = 4


def _clear_proxy_environment() -> None:
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ[name] = ""
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def _normalize_minute_frame(
    frame: pd.DataFrame,
    instrument: str,
    source: str = "eastmoney_5min_via_akshare",
) -> pd.DataFrame:
    mapping = {
        "时间": "datetime",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "涨跌幅": "return_pct",
        "涨跌额": "change",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude_pct",
        "换手率": "turnover_rate_pct",
        "day": "datetime",
    }
    result = frame.rename(columns=mapping).copy()
    if result.empty:
        return result
    result.insert(0, "instrument", instrument)
    result["datetime"] = pd.to_datetime(result["datetime"], errors="coerce")
    for column in mapping.values():
        if column != "datetime" and column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    result["source"] = source
    result["knowledge_time"] = result["datetime"]
    return (
        result.dropna(subset=["datetime", "open", "close"])
        .drop_duplicates(["instrument", "datetime"], keep="last")
        .sort_values("datetime")
    )


def fetch_minute_history(
    instrument: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    retries: int = 3,
) -> pd.DataFrame:
    MINUTE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = MINUTE_CACHE_DIR / f"{instrument}.parquet"
    cached = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    if not cached.empty:
        cached["datetime"] = pd.to_datetime(cached["datetime"])
        cached_start = cached["datetime"].min()
        cached_end = cached["datetime"].max()
        if cached_start <= start and cached_end >= end:
            return cached.loc[cached["datetime"].between(start, end)].copy()

    code = instrument[2:]
    errors: list[str] = []
    providers = ("eastmoney", "sina")
    for provider in providers:
        provider_retries = 1 if provider == "eastmoney" else max(1, retries - 1)
        for attempt in range(1, provider_retries + 1):
            try:
                if provider == "eastmoney":
                    raw = ak.stock_zh_a_hist_min_em(
                        symbol=code,
                        start_date=start.strftime("%Y-%m-%d %H:%M:%S"),
                        end_date=end.strftime("%Y-%m-%d %H:%M:%S"),
                        period="5",
                        adjust="qfq",
                    )
                    source = "eastmoney_5min_via_akshare"
                else:
                    raw = ak.stock_zh_a_minute(
                        symbol=instrument.lower(),
                        period="5",
                        adjust="qfq",
                    )
                    source = "sina_5min_via_akshare"
                fresh = _normalize_minute_frame(raw, instrument, source=source)
                fresh = fresh.loc[fresh["datetime"].between(start, end)]
                if fresh.empty:
                    raise ValueError(f"{provider} returned no bars for requested interval")
                combined = pd.concat([cached, fresh], ignore_index=True) if not cached.empty else fresh
                combined = combined.drop_duplicates(["instrument", "datetime"], keep="last").sort_values("datetime")
                temporary = path.with_suffix(".tmp.parquet")
                combined.to_parquet(temporary, index=False, compression="zstd")
                temporary.replace(path)
                return combined.loc[combined["datetime"].between(start, end)].copy()
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
                if attempt < provider_retries:
                    time.sleep(attempt)
    raise RuntimeError(f"minute fetch failed for {instrument}: {' | '.join(errors)}")


def minute_features_asof(
    frame: pd.DataFrame,
    signal_date: pd.Timestamp,
    signal_time: str = "14:00",
    trailing_days: int = 5,
) -> dict[str, float] | None:
    """Compute features using bars available no later than the signal time."""

    data = frame.copy()
    data["datetime"] = pd.to_datetime(data["datetime"])
    date = signal_date.normalize()
    cutoff = pd.Timestamp(f"{date:%Y-%m-%d} {signal_time}:00")
    today = data.loc[(data["datetime"].dt.normalize() == date) & (data["datetime"] <= cutoff)]
    if today.empty or today["datetime"].max() < cutoff:
        return None
    prior_dates = sorted(item for item in data["datetime"].dt.normalize().unique() if item < date)
    if not prior_dates:
        return None
    previous = data.loc[data["datetime"].dt.normalize() == prior_dates[-1]]
    if previous.empty:
        return None

    current_price = float(today.iloc[-1]["close"])
    day_open = float(today.iloc[0]["open"])
    day_high = float(today["high"].max())
    previous_close = float(previous.iloc[-1]["close"])
    if min(current_price, day_open, day_high, previous_close) <= 0:
        return None

    prior_amounts = []
    for prior_date in prior_dates[-trailing_days:]:
        prior_cutoff = pd.Timestamp(f"{prior_date:%Y-%m-%d} {signal_time}:00")
        prior = data.loc[
            (data["datetime"].dt.normalize() == prior_date)
            & (data["datetime"] <= prior_cutoff)
        ]
        if not prior.empty:
            prior_amounts.append(float(prior["amount"].sum()))
    amount_to_signal = float(today["amount"].sum())
    average_prior_amount = float(np.mean(prior_amounts)) if prior_amounts else np.nan
    amount_ratio = amount_to_signal / average_prior_amount if average_prior_amount > 0 else np.nan

    late_cutoff = cutoff - timedelta(minutes=30)
    late_reference = today.loc[today["datetime"] <= late_cutoff]
    late_price = float(late_reference.iloc[-1]["close"]) if not late_reference.empty else day_open
    return {
        "price_1400": current_price,
        "previous_close": previous_close,
        "intraday_return": current_price / previous_close - 1.0,
        "from_open": current_price / day_open - 1.0,
        "from_high": current_price / day_high - 1.0,
        "late_momentum_30m": current_price / late_price - 1.0,
        "amount_to_signal": amount_to_signal,
        "amount_ratio": amount_ratio,
    }


def executable_prices(
    frame: pd.DataFrame,
    signal_date: pd.Timestamp,
    trading_dates: list[pd.Timestamp],
    entry_bar_time: str = "14:45",
) -> dict[str, float] | None:
    data = frame.copy()
    data["datetime"] = pd.to_datetime(data["datetime"])
    date = signal_date.normalize()
    entry_time = pd.Timestamp(f"{date:%Y-%m-%d} {entry_bar_time}:00")
    entry = data.loc[(data["datetime"].dt.normalize() == date) & (data["datetime"] >= entry_time)]
    if entry.empty:
        return None
    try:
        position = trading_dates.index(date)
    except ValueError:
        return None
    result = {"entry": float(entry.iloc[0]["open"])}
    for horizon in (1, 5):
        if position + horizon >= len(trading_dates):
            result[f"exit_{horizon}d"] = np.nan
            continue
        exit_date = trading_dates[position + horizon]
        exit_bars = data.loc[data["datetime"].dt.normalize() == exit_date]
        result[f"exit_{horizon}d"] = float(exit_bars.iloc[0]["open"]) if not exit_bars.empty else np.nan
    return result


def score_intraday_candidates(frame: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    result = frame.copy()
    result["eligible_intraday"] = (
        result["intraday_return"].between(config.min_intraday_return, config.max_intraday_return)
        & (result["from_open"] >= config.min_from_open)
        & (result["from_high"] >= config.min_from_high)
        & (result["amount_to_signal"] >= config.min_amount_to_signal)
        & result["amount_ratio"].between(config.min_amount_ratio, config.max_amount_ratio)
    )
    result["rank_prior"] = result["prior_score"].rank(pct=True)
    result["rank_relative_strength"] = result["intraday_return"].rank(pct=True)
    structure = (
        0.50 * result["from_open"].rank(pct=True)
        + 0.30 * result["from_high"].rank(pct=True)
        + 0.20 * result["late_momentum_30m"].rank(pct=True)
    )
    amount_quality = 1.0 - np.log(result["amount_ratio"].clip(0.25, 8.0) / 1.2).abs() / np.log(8.0)
    volume_quality = 0.50 * amount_quality.clip(0, 1) + 0.50 * result["amount_to_signal"].rank(pct=True)
    overheat = ((result["intraday_return"] - 0.05).clip(lower=0) / 0.02).clip(0, 1)
    result["intraday_score"] = (
        0.35 * result["rank_prior"]
        + 0.25 * result["rank_relative_strength"]
        + 0.15 * structure
        + 0.15 * volume_quality
        + 0.10 * (1.0 - overheat)
    )
    return result


def _net_return(exit_price: float, entry_price: float, config: BacktestConfig) -> float:
    if not np.isfinite(exit_price) or not np.isfinite(entry_price) or entry_price <= 0:
        return np.nan
    return float(exit_price / entry_price - 1.0 - config.open_cost - config.close_cost)


def _summary(values: pd.Series) -> dict[str, Any]:
    clean = values.dropna()
    if clean.empty:
        return {"count": 0, "mean": None, "median": None, "win_rate": None}
    return {
        "count": int(len(clean)),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "trimmed_mean": float(clean.sort_values().iloc[1:-1].mean()) if len(clean) >= 5 else None,
        "win_rate": float((clean > 0).mean()),
        "worst": float(clean.min()),
        "best": float(clean.max()),
    }


def _comparison_report(portfolios: pd.DataFrame) -> dict[str, Any]:
    if portfolios.empty:
        return {}
    pivot = portfolios.pivot(index="date", columns="strategy", values=["return_1d", "return_5d"])
    report: dict[str, Any] = {}
    for challenger in ("intraday_top", "naive_momentum_top"):
        if challenger not in portfolios["strategy"].unique():
            continue
        challenger_report: dict[str, Any] = {}
        for horizon in ("return_1d", "return_5d"):
            excess = pivot[(horizon, challenger)] - pivot[(horizon, "broad_candidates")]
            challenger_report[horizon + "_excess_vs_broad"] = _summary(excess)
        report[challenger] = challenger_report

    dates = sorted(portfolios["date"].unique())
    midpoint = len(dates) // 2
    subperiods = {"first_half": set(dates[:midpoint]), "second_half": set(dates[midpoint:])}
    report["subperiods"] = {}
    for label, selected_dates in subperiods.items():
        part = portfolios.loc[portfolios["date"].isin(selected_dates)]
        report["subperiods"][label] = {}
        for strategy, group in part.groupby("strategy"):
            report["subperiods"][label][strategy] = {
                "return_1d": _summary(group["return_1d"]),
                "return_5d": _summary(group["return_5d"]),
            }
    return report


def run_backtest(config: BacktestConfig) -> dict[str, Any]:
    _clear_proxy_environment()
    init_qlib()
    calendar = get_calendar()
    if len(calendar) < config.days + 80:
        raise ValueError("Qlib calendar is too short")
    signal_dates = [pd.Timestamp(item) for item in calendar[-config.days:]]
    previous_dates = [pd.Timestamp(calendar[int(calendar.get_loc(date)) - 1]) for date in signal_dates]
    load_start = pd.Timestamp(calendar[max(0, int(calendar.get_loc(previous_dates[0])) - 75)])
    panel = load_factor_panel("csi800", str(load_start.date()), str(previous_dates[-1].date()))
    funnel_config = FunnelConfig(top_n=config.base_top_n)

    candidates_by_date: dict[pd.Timestamp, pd.DataFrame] = {}
    all_instruments: set[str] = set()
    for signal_date, previous_date in zip(signal_dates, previous_dates):
        selected = select_candidates(panel, previous_date, funnel_config)
        candidates_by_date[signal_date.normalize()] = selected
        all_instruments.update(selected.index.astype(str))

    minute_start = signal_dates[0] - pd.Timedelta(days=12)
    minute_end = signal_dates[-1] + pd.Timedelta(days=12)
    minute_frames: dict[str, pd.DataFrame] = {}
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=config.workers) as executor:
        futures = {
            executor.submit(fetch_minute_history, instrument, minute_start, minute_end): instrument
            for instrument in sorted(all_instruments)
        }
        for number, future in enumerate(as_completed(futures), 1):
            instrument = futures[future]
            try:
                minute_frames[instrument] = future.result()
            except Exception as exc:
                failures[instrument] = str(exc)
            if number == 1 or number % 25 == 0:
                print(
                    f"  minute data {number}/{len(futures)} ok={len(minute_frames)} failed={len(failures)}",
                    flush=True,
                )

    all_dates = sorted(
        {
            pd.Timestamp(item).normalize()
            for frame in minute_frames.values()
            for item in pd.to_datetime(frame["datetime"]).tolist()
        }
    )
    stock_rows = []
    portfolio_rows = []
    for signal_date in signal_dates:
        date = signal_date.normalize()
        selected = candidates_by_date[date]
        rows = []
        for instrument, prior in selected.iterrows():
            minutes = minute_frames.get(str(instrument))
            if minutes is None or minutes.empty:
                continue
            features = minute_features_asof(minutes, date, config.signal_time)
            prices = executable_prices(minutes, date, all_dates, config.entry_bar_time)
            if features is None or prices is None:
                continue
            row = {
                "date": str(date.date()),
                "instrument": str(instrument),
                "prior_score": float(prior.get("leader_score", prior.get("score", np.nan))),
                **features,
                **prices,
            }
            row["return_1d"] = _net_return(row["exit_1d"], row["entry"], config)
            row["return_5d"] = _net_return(row["exit_5d"], row["entry"], config)
            rows.append(row)
        if not rows:
            continue
        cross_section = score_intraday_candidates(pd.DataFrame(rows), config)
        ranked = cross_section.loc[cross_section["eligible_intraday"]].sort_values("intraday_score", ascending=False)
        intraday = ranked.head(config.final_top_n)
        momentum = cross_section.sort_values("intraday_return", ascending=False).head(config.final_top_n)
        strategies = {
            "broad_candidates": cross_section,
            "intraday_top": intraday,
            "naive_momentum_top": momentum,
        }
        for strategy, holdings in strategies.items():
            portfolio_rows.append(
                {
                    "date": str(date.date()),
                    "strategy": strategy,
                    "selected": int(len(holdings)),
                    "return_1d": float(holdings["return_1d"].mean()) if len(holdings) else np.nan,
                    "return_5d": float(holdings["return_5d"].mean()) if len(holdings) else np.nan,
                }
            )
        cross_section["selected_intraday"] = cross_section["instrument"].isin(intraday["instrument"])
        stock_rows.extend(cross_section.to_dict("records"))

    portfolios = pd.DataFrame(portfolio_rows)
    summaries: dict[str, Any] = {}
    if not portfolios.empty:
        for strategy, group in portfolios.groupby("strategy"):
            summaries[strategy] = {
                "return_1d": _summary(group["return_1d"]),
                "return_5d": _summary(group["return_5d"]),
            }
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": asdict(config),
        "methodology": {
            "candidate_signal": "T-1 close using only daily history available then",
            "intraday_signal": f"T {config.signal_time}, five-minute bars timestamp <= signal",
            "entry": f"T {config.entry_bar_time} bar open, after {config.decision_cutoff} UZI deadline",
            "exits": "T+1 and T+5 first five-minute bar open",
            "costs": f"open {config.open_cost:.4%}, close {config.close_cost:.4%}",
            "weights": "fixed before observing results; no parameter search",
            "uzi_limitation": "historical qualitative UZI not replayed; candidate layer only",
        },
        "data_quality": {
            "requested_instruments": len(all_instruments),
            "minute_success": len(minute_frames),
            "minute_failures": failures,
        },
        "summary": summaries,
        "comparisons": _comparison_report(portfolios),
        "portfolio_periods": portfolio_rows,
        "stock_records": stock_rows,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest the leakage-safe 14:00 candidate selector")
    parser.add_argument("--days", type=int, default=BacktestConfig.days)
    parser.add_argument("--base-top", type=int, default=BacktestConfig.base_top_n)
    parser.add_argument("--final-top", type=int, default=BacktestConfig.final_top_n)
    parser.add_argument("--workers", type=int, default=BacktestConfig.workers)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "intraday_candidate_backtest_latest.json")
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    config = BacktestConfig(
        days=args.days,
        base_top_n=args.base_top,
        final_top_n=args.final_top,
        workers=args.workers,
    )
    result = run_backtest(config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"result: {args.output}")
    return result


if __name__ == "__main__":
    main()
