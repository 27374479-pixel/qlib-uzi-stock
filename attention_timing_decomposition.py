"""Decompose book/attention signals into overnight and post-open return windows.

A daily-close state can only justify a *new* position at the next executable
price.  If apparent alpha lives in T-close -> T+1-open, it is not monetizable by
that new position.  This script therefore separates attention/leader cohorts
into:

* overnight_gap: T close -> T+1 open;
* entry_day_intraday: T+1 open -> T+1 close;
* second_overnight: T+1 close -> T+2 open;
* post_open_1d: T+1 open -> T+2 open, after round-trip cost.

It is a diagnostic, not a trading strategy.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

import book_alpha_daily_screen as features
from book_alpha_daily_screen_v3 import enforce_true_listing_policy
from daily_event_role_backtest import (
    Config as EventConfig,
    add_roles,
    build_market_state,
    build_theme_state,
    load_panel,
)

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Config:
    universe: str = "csi800"
    start: str = "2015-01-01"
    end: str = "2026-09-03"
    oos_start: str = "2023-01-01"
    round_trip_cost: float = 0.0018
    bootstrap_samples: int = 5000
    seed: int = 20260904
    output: str = "output/attention_timing_decomposition_v1.json"


def _ci(values: pd.Series, samples: int, seed: int) -> list[float | None]:
    values = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    if len(values) < 8:
        return [None, None]
    rng = np.random.default_rng(seed)
    means = np.empty(samples)
    for i in range(samples):
        means[i] = rng.choice(values, len(values), replace=True).mean()
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def prepare(config: Config) -> pd.DataFrame:
    base = EventConfig(universe=config.universe, start=config.start, end=config.end)
    panel, _ = load_panel(base)
    market = build_market_state(panel).rename(columns={"broken_ratio": "broken_ratio_market"})
    theme = build_theme_state(panel)
    frame = add_roles(panel, theme, market)
    frame = features.add_research_features(frame)
    frame, _ = enforce_true_listing_policy(frame)
    frame = frame.sort_values(["instrument", "date"]).reset_index(drop=True)
    by_stock = frame.groupby("instrument", sort=False)
    frame["next_open"] = by_stock["open"].shift(-1)
    frame["next_close"] = by_stock["close"].shift(-1)
    frame["next2_open"] = by_stock["open"].shift(-2)
    frame["next_low"] = by_stock["low"].shift(-1)
    frame["next_upper_limit"] = by_stock["upper_limit"].shift(-1)
    frame["entry_filled"] = (
        frame["next_open"].notna()
        & frame["next_low"].notna()
        & ~(
            (frame["next_open"] >= frame["next_upper_limit"] - 0.011)
            & (frame["next_low"] >= frame["next_upper_limit"] - 0.011)
        )
    )
    frame["overnight_gap"] = frame["next_open"] / frame["close"] - 1.0
    frame["entry_day_intraday"] = frame["next_close"] / frame["next_open"] - 1.0
    frame["second_overnight"] = frame["next2_open"] / frame["next_close"] - 1.0
    frame["post_open_1d"] = (frame["next2_open"] / frame["next_open"] - 1.0 - config.round_trip_cost).where(frame["entry_filled"])
    return frame


def cohorts() -> dict[str, Callable[[pd.DataFrame], pd.Series]]:
    core = lambda f: f["core"].fillna(False).astype(bool) & ~f["one_word"].fillna(False).astype(bool)
    return {
        "all_eligible": lambda f: pd.Series(True, index=f.index),
        "current_touch_any": lambda f: f["touch_up"].fillna(False).astype(bool),
        "current_first_touch20": lambda f: f["touch_up"].fillna(False).astype(bool) & f["prior_touch20"].fillna(0).eq(0),
        "current_repeated_touch20_ge3": lambda f: f["touch_up"].fillna(False).astype(bool) & f["prior_touch20"].fillna(0).ge(3),
        "current_seal": lambda f: f["seal_up"].fillna(False).astype(bool) & ~f["one_word"].fillna(False).astype(bool),
        "active_core": lambda f: core(f) & (f["prior_touch20"].fillna(0).gt(0) | f["prior_seal5"].fillna(0).gt(0)),
        "divergence_survivor": lambda f: f["divergence"].fillna(False).astype(bool)
        & (f["prior_touch20"].fillna(0).gt(0)) & f["ret_rank"].fillna(0).ge(0.75),
        "climax_core": lambda f: core(f) & f["climax"].fillna(False).astype(bool),
        "repair_core": lambda f: core(f) & f["repair"].fillna(False).astype(bool),
    }


def metrics(sample: pd.DataFrame, config: Config, seed: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "n": int(len(sample)),
        "active_days": int(sample["date"].nunique()),
    }
    for offset, column in enumerate(("overnight_gap", "entry_day_intraday", "second_overnight", "post_open_1d")):
        values = pd.to_numeric(sample[column], errors="coerce").dropna()
        result[column] = {
            "n": int(len(values)),
            "mean": float(values.mean()) if len(values) else None,
            "median": float(values.median()) if len(values) else None,
            "positive_rate": float((values > 0).mean()) if len(values) else None,
            "bootstrap95": _ci(values, config.bootstrap_samples, seed + offset),
        }
    overnight = result["overnight_gap"].get("mean")
    post = result["post_open_1d"].get("mean")
    if overnight is not None and overnight > 0 and post is not None and post <= 0:
        result["timing_classification"] = "PRE_ENTRY_PREMIUM_ONLY"
    elif post is not None and post > 0:
        result["timing_classification"] = "POST_OPEN_MONETIZABLE_CANDIDATE"
    else:
        result["timing_classification"] = "NO_POSITIVE_POST_OPEN_EDGE"
    return result


def run(config: Config) -> dict[str, Any]:
    frame = prepare(config)
    split = pd.Timestamp(config.oos_start)
    report: dict[str, Any] = {
        "config": asdict(config),
        "question": "Does observed leader/limit attention pay before or after the next executable open?",
        "cohorts": {},
        "interpretation_rule": "Positive T-close->T+1-open is not a new-entry alpha for a T-close signal. New-entry evidence requires post-open return after costs.",
    }
    for index, (name, selector) in enumerate(cohorts().items()):
        mask = selector(frame).fillna(False)
        sample = frame.loc[mask]
        report["cohorts"][name] = {
            "all": metrics(sample, config, config.seed + index * 20),
            "oos": metrics(sample.loc[sample["date"] >= split], config, config.seed + index * 20 + 10),
        }
    output = ROOT / config.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({name: item["oos"]["timing_classification"] for name, item in report["cohorts"].items()}, ensure_ascii=False, indent=2))
    return report


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Decompose attention/leader alpha by execution timing")
    parser.add_argument("--universe", default=Config.universe)
    parser.add_argument("--start", default=Config.start)
    parser.add_argument("--end", default=Config.end)
    parser.add_argument("--oos-start", default=Config.oos_start)
    parser.add_argument("--round-trip-cost", type=float, default=Config.round_trip_cost)
    parser.add_argument("--bootstrap-samples", type=int, default=Config.bootstrap_samples)
    parser.add_argument("--seed", type=int, default=Config.seed)
    parser.add_argument("--output", default=Config.output)
    return Config(**vars(parser.parse_args()))


if __name__ == "__main__":
    run(parse_args())
