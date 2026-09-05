"""Validate v3 PASS hypotheses on dates with executable five-minute data.

This is intentionally a *timing* study, not a new factor search.

Rules:
- Read canonical v3 verdicts from output/book_alpha_daily_screen_v3.json.
- Keep only hypotheses with overall_verdict == PASS.
- Reconstruct the daily feature frame causally and apply the original frozen
  selectors; no re-fitting and no threshold search.
- Evaluate only signal dates for which selected names have complete local 5m
  bars at the requested entry time and on the next trading session.
- Compare late-day executable entries (14:00/14:30/14:45/14:55 by default)
  with next-session open/10:00/close exits.
- Report per-hypothesis and all-PASS-union results after explicit costs.

The script never fetches data from the network. It consumes the repository's
existing local minute cache and therefore makes missing-data coverage explicit
instead of silently changing the sample.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

import book_alpha_daily_screen as core
from book_alpha_daily_screen_v3 import enforce_true_listing_policy
from daily_event_role_backtest import (
    Config as EventConfig,
    add_roles,
    build_market_state,
    build_theme_state,
    load_panel,
)

ROOT = Path(__file__).resolve().parent
PASS_REPORT = ROOT / "output" / "book_alpha_daily_screen_v3.json"

# Supported local caches. The first usable file wins.
MINUTE_DIRS = (
    ROOT / "data_lake" / "raw" / "eastmoney" / "equity_5min",
    ROOT / "data_lake" / "raw" / "baostock" / "equity_5min",
    ROOT / "data_lake" / "raw" / "sina" / "equity_5min",
)


@dataclass(frozen=True)
class Config:
    universe: str = "csi800"
    start: str = "2015-01-01"
    end: str = "2026-09-03"
    entry_times: tuple[str, ...] = ("14:00", "14:30", "14:45", "14:55")
    exit_times: tuple[str, ...] = ("09:30", "10:00", "15:00")
    buy_cost: float = 0.0003
    sell_cost: float = 0.0013
    min_complete_names_per_day: int = 1
    require_all_selected_names_complete: bool = True
    bootstrap_samples: int = 5000
    seed: int = 20260905
    output: str = "output/v4_intraday_survivor_validation.json"


def _load_pass_ids() -> list[str]:
    if not PASS_REPORT.exists():
        raise FileNotFoundError(f"missing canonical v3 report: {PASS_REPORT}")
    report = json.loads(PASS_REPORT.read_text(encoding="utf-8"))
    ids = [
        key for key, item in report.get("hypotheses", {}).items()
        if item.get("overall_verdict") == "PASS"
    ]
    if not ids:
        raise RuntimeError("canonical v3 report contains no PASS hypotheses")
    return ids


def _prepare_daily(config: Config) -> pd.DataFrame:
    event = EventConfig(universe=config.universe, start=config.start, end=config.end)
    panel, _ = load_panel(event)
    market = build_market_state(panel).rename(columns={"broken_ratio": "broken_ratio_market"})
    theme = build_theme_state(panel)
    frame = add_roles(panel, theme, market)
    frame = core.add_research_features(frame)
    frame, _ = enforce_true_listing_policy(frame)
    return frame.sort_values(["instrument", "date"]).reset_index(drop=True)


def _hypothesis_map() -> dict[str, Any]:
    return {item.id: item for item in core.hypotheses()}


def _candidate_rows(frame: pd.DataFrame, pass_ids: list[str]) -> pd.DataFrame:
    mapping = _hypothesis_map()
    pieces: list[pd.DataFrame] = []
    for hypothesis_id in pass_ids:
        if hypothesis_id not in mapping:
            raise KeyError(f"PASS hypothesis {hypothesis_id} not found in current frozen definitions")
        h = mapping[hypothesis_id]
        selected = frame.loc[h.selector(frame).fillna(False), ["date", "instrument"]].copy()
        selected["hypothesis_id"] = hypothesis_id
        pieces.append(selected)
    if not pieces:
        return pd.DataFrame(columns=["date", "instrument", "hypothesis_id"])
    return pd.concat(pieces, ignore_index=True).drop_duplicates()


def _minute_path(instrument: str) -> Path | None:
    for directory in MINUTE_DIRS:
        path = directory / f"{instrument}.parquet"
        if path.exists():
            return path
    return None


def _normalize_minute(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    mapping = {
        "时间": "datetime", "day": "datetime", "date": "datetime",
        "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
        "成交额": "amount", "成交量": "volume",
    }
    result = result.rename(columns={k: v for k, v in mapping.items() if k in result.columns})
    if "datetime" not in result.columns:
        raise ValueError("minute file has no datetime column")
    result["datetime"] = pd.to_datetime(result["datetime"], errors="coerce")
    for column in ("open", "high", "low", "close", "amount", "volume"):
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.dropna(subset=["datetime", "open", "close"]).sort_values("datetime")


def _load_minute(instrument: str, cache: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    if instrument in cache:
        return cache[instrument]
    path = _minute_path(instrument)
    if path is None:
        cache[instrument] = pd.DataFrame()
        return None
    try:
        frame = _normalize_minute(pd.read_parquet(path))
    except Exception:
        frame = pd.DataFrame()
    cache[instrument] = frame
    return frame if not frame.empty else None


def _trading_dates(frame: pd.DataFrame) -> list[pd.Timestamp]:
    return [pd.Timestamp(x).normalize() for x in sorted(pd.to_datetime(frame["date"]).dt.normalize().unique())]


def _bar_price(
    minute: pd.DataFrame,
    date: pd.Timestamp,
    time_text: str,
    side: str,
) -> float | None:
    target = pd.Timestamp(f"{date:%Y-%m-%d} {time_text}:00")
    day = minute.loc[minute["datetime"].dt.normalize() == date]
    if day.empty:
        return None
    if side == "entry":
        bars = day.loc[day["datetime"] >= target]
        if bars.empty:
            return None
        return float(bars.iloc[0]["open"])
    if time_text == "15:00":
        return float(day.iloc[-1]["close"])
    bars = day.loc[day["datetime"] >= target]
    if bars.empty:
        return None
    return float(bars.iloc[0]["open"])


def _day_is_complete_for_selection(
    selected: pd.DataFrame,
    date: pd.Timestamp,
    next_date: pd.Timestamp,
    entry_time: str,
    exit_times: tuple[str, ...],
    minute_cache: dict[str, pd.DataFrame],
    config: Config,
) -> tuple[bool, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    for row in selected.itertuples(index=False):
        minute = _load_minute(row.instrument, minute_cache)
        if minute is None:
            records.append({"instrument": row.instrument, "hypothesis_id": row.hypothesis_id, "status": "missing_file"})
            continue
        entry = _bar_price(minute, date, entry_time, "entry")
        exits = {t: _bar_price(minute, next_date, t, "exit") for t in exit_times}
        status = "ok" if entry is not None and all(v is not None for v in exits.values()) else "incomplete_bars"
        records.append({
            "instrument": row.instrument,
            "hypothesis_id": row.hypothesis_id,
            "status": status,
            "entry": entry,
            **{f"exit_{t}": v for t, v in exits.items()},
        })
    complete = [r for r in records if r["status"] == "ok"]
    if config.require_all_selected_names_complete:
        accepted = len(complete) == len(records) and len(complete) >= config.min_complete_names_per_day
    else:
        accepted = len(complete) >= config.min_complete_names_per_day
    return accepted, complete


def _bootstrap_ci(values: pd.Series, config: Config, seed: int) -> list[float | None]:
    clean = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    if len(clean) < 8:
        return [None, None]
    rng = np.random.default_rng(seed)
    means = np.empty(config.bootstrap_samples)
    for i in range(config.bootstrap_samples):
        means[i] = rng.choice(clean, len(clean), replace=True).mean()
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def _summary(values: pd.Series, config: Config, seed: int) -> dict[str, Any]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {"n": 0, "mean": None, "median": None, "win_rate": None, "bootstrap95": [None, None]}
    trimmed = clean.sort_values()
    if len(trimmed) >= 10:
        k = max(1, int(round(len(trimmed) * 0.10)))
        trimmed = trimmed.iloc[k:-k]
    return {
        "n": int(len(clean)),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "trimmed_mean_10pct": float(trimmed.mean()) if len(trimmed) else None,
        "win_rate": float((clean > 0).mean()),
        "worst": float(clean.min()),
        "best": float(clean.max()),
        "bootstrap95": _bootstrap_ci(clean, config, seed),
    }


def run(config: Config) -> dict[str, Any]:
    pass_ids = _load_pass_ids()
    daily = _prepare_daily(config)
    candidates = _candidate_rows(daily, pass_ids)
    dates = _trading_dates(daily)
    date_to_next = {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}
    minute_cache: dict[str, pd.DataFrame] = {}

    rows: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {}
    for entry_index, entry_time in enumerate(config.entry_times):
        accepted_days = 0
        rejected_days = 0
        for date, selected in candidates.groupby("date"):
            date = pd.Timestamp(date).normalize()
            next_date = date_to_next.get(date)
            if next_date is None:
                continue
            accepted, complete = _day_is_complete_for_selection(
                selected, date, next_date, entry_time, config.exit_times, minute_cache, config
            )
            if not accepted:
                rejected_days += 1
                continue
            accepted_days += 1
            for item in complete:
                entry = float(item["entry"])
                for exit_time in config.exit_times:
                    exit_price = float(item[f"exit_{exit_time}"])
                    net = exit_price / entry - 1.0 - config.buy_cost - config.sell_cost
                    rows.append({
                        "date": str(date.date()),
                        "next_date": str(next_date.date()),
                        "instrument": item["instrument"],
                        "hypothesis_id": item["hypothesis_id"],
                        "entry_time": entry_time,
                        "exit_time": exit_time,
                        "net_return": float(net),
                    })
        coverage[entry_time] = {"accepted_days": accepted_days, "rejected_days": rejected_days}

    trades = pd.DataFrame(rows)
    report: dict[str, Any] = {
        "config": asdict(config),
        "pass_hypotheses": pass_ids,
        "coverage": coverage,
        "methodology": {
            "signal": "original frozen v3 PASS hypothesis selectors on completed daily data",
            "sample_gate": "only dates with required local 5m bars; no network backfill",
            "entry": "first 5m bar open at or after requested late-day time",
            "exit": "next trading session first 5m bar at/after requested time; 15:00 uses final close",
            "cost": config.buy_cost + config.sell_cost,
            "anti_leakage": "daily selector has no same-day intraday inputs; minute price only determines execution after signal",
        },
        "results": {},
    }
    if not trades.empty:
        strategies = [("ALL_PASS", trades)] + [(h, g) for h, g in trades.groupby("hypothesis_id")]
        for s_idx, (strategy, sample) in enumerate(strategies):
            report["results"][strategy] = {}
            for e_idx, entry_time in enumerate(config.entry_times):
                report["results"][strategy][entry_time] = {}
                for x_idx, exit_time in enumerate(config.exit_times):
                    subset = sample.loc[(sample["entry_time"] == entry_time) & (sample["exit_time"] == exit_time)]
                    # Portfolio unit is date, equal-weight across names selected that day.
                    daily_returns = subset.groupby("date")["net_return"].mean() if not subset.empty else pd.Series(dtype=float)
                    report["results"][strategy][entry_time][exit_time] = {
                        "trade_level": _summary(subset["net_return"] if not subset.empty else pd.Series(dtype=float), config, config.seed + s_idx * 100 + e_idx * 10 + x_idx),
                        "date_equal_weight": _summary(daily_returns, config, config.seed + 5000 + s_idx * 100 + e_idx * 10 + x_idx),
                        "active_days": int(len(daily_returns)),
                    }
    output = ROOT / config.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"pass_hypotheses": pass_ids, "coverage": coverage}, ensure_ascii=False, indent=2))
    return report


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="v4 timing validation for v3 PASS survivors")
    parser.add_argument("--universe", default=Config.universe)
    parser.add_argument("--start", default=Config.start)
    parser.add_argument("--end", default=Config.end)
    parser.add_argument("--entry-times", default=",".join(Config.entry_times))
    parser.add_argument("--exit-times", default=",".join(Config.exit_times))
    parser.add_argument("--buy-cost", type=float, default=Config.buy_cost)
    parser.add_argument("--sell-cost", type=float, default=Config.sell_cost)
    parser.add_argument("--min-complete-names-per-day", type=int, default=Config.min_complete_names_per_day)
    parser.add_argument("--allow-partial-days", action="store_true")
    parser.add_argument("--bootstrap-samples", type=int, default=Config.bootstrap_samples)
    parser.add_argument("--seed", type=int, default=Config.seed)
    parser.add_argument("--output", default=Config.output)
    args = vars(parser.parse_args())
    args["entry_times"] = tuple(x.strip() for x in args["entry_times"].split(",") if x.strip())
    args["exit_times"] = tuple(x.strip() for x in args["exit_times"].split(",") if x.strip())
    args["require_all_selected_names_complete"] = not args.pop("allow_partial_days")
    return Config(**args)


if __name__ == "__main__":
    run(parse_args())
