"""Independent A-share evidence challengers for the book-derived hypotheses.

These tests are intentionally *not* attributed to any trader.  They challenge
book heuristics with mechanisms documented in external A-share research:
attention saturation/reversal, limit-hit contamination of momentum, lottery
crowding, and distinct market-vs-speculative emotion layers.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import book_alpha_daily_screen as core
from attention_timing_decomposition import Config as TimingConfig, prepare as prepare_timing

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
    output: str = "output/external_challenger_daily_screen_v1.json"


def add_challenger_features(frame: pd.DataFrame, cost: float) -> pd.DataFrame:
    frame = frame.sort_values(["instrument", "date"]).copy()
    log_ret = np.log(frame["close"].where(frame["close"] > 0) / frame["preclose"].where(frame["preclose"] > 0))
    frame["clean_log_ret"] = log_ret.where(~frame["touch_up"].fillna(False), 0.0)
    by_stock = frame.groupby("instrument", sort=False)
    frame["clean_mom20"] = np.expm1(by_stock["clean_log_ret"].transform(lambda x: x.rolling(20, min_periods=15).sum()))
    frame["clean_mom60"] = np.expm1(by_stock["clean_log_ret"].transform(lambda x: x.rolling(60, min_periods=40).sum()))
    frame["hit_count20"] = by_stock["touch_up"].transform(lambda x: x.astype(float).rolling(20, min_periods=10).sum())
    frame["hit_count60"] = by_stock["touch_up"].transform(lambda x: x.astype(float).rolling(60, min_periods=30).sum())
    frame["raw_mom20_rank"] = frame.groupby("date")["ret20"].rank(pct=True)
    frame["clean_mom20_rank"] = frame.groupby("date")["clean_mom20"].rank(pct=True)
    frame["vol10_rank"] = frame.groupby("date")["vol10"].rank(pct=True)
    frame["turnover_market_rank"] = frame.groupby("date")["turnover_rate_pct"].rank(pct=True)
    return core.attach_forward_returns(frame, cost)


def _active_core(f: pd.DataFrame) -> pd.Series:
    return (
        f["core"].fillna(False).astype(bool)
        & ~f["one_word"].fillna(False).astype(bool)
        & (f["prior_touch20"].fillna(0).gt(0) | f["prior_seal5"].fillna(0).gt(0))
    )


def challenger_masks(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    active = _active_core(frame)
    return {
        "X01_attention_saturation": {
            "selected": active & frame["hit_count20"].between(1, 2),
            "control": active & frame["hit_count20"].ge(4),
            "direction": 1,
            "meaning": "fresh/limited attention should beat saturated repeated limit-hit attention",
        },
        "X02_limit_adjusted_momentum": {
            "selected": frame["raw_mom20_rank"].ge(0.80) & frame["clean_mom20_rank"].ge(0.80) & frame["hit_count20"].le(1),
            "control": frame["raw_mom20_rank"].ge(0.80) & frame["clean_mom20_rank"].lt(0.80) & frame["hit_count20"].ge(3),
            "direction": 1,
            "meaning": "smooth strong momentum should beat raw momentum manufactured by repeated limit hits",
        },
        "X04_lottery_crowding_veto": {
            "selected": frame["close"].lt(10) & frame["hit_count20"].ge(3) & frame["vol10_rank"].ge(0.80) & frame["turnover_market_rank"].ge(0.80),
            "control": frame["close"].lt(10) & frame["hit_count20"].le(1) & frame["vol10_rank"].between(0.30, 0.70),
            "direction": -1,
            "meaning": "low-price high-attention lottery crowding should underperform less-crowded low-price controls",
        },
    }


def emotion_quadrants(frame: pd.DataFrame, split: pd.Timestamp, screen_config: core.ScreenConfig) -> dict[str, Any]:
    oos = frame.loc[frame["date"] >= split].copy()
    oos = oos.loc[_active_core(oos)].copy()
    if oos.empty:
        return {}
    oos["market_layer"] = np.where(oos["breadth"].fillna(0) > 0, "market_up", "market_down")
    speculative = (oos["money_effect"].fillna(0) > 0.005) & (oos["broken_ratio_market"].fillna(1) < 0.50)
    oos["speculative_layer"] = np.where(speculative, "spec_strong", "spec_weak")
    result: dict[str, Any] = {}
    for (market_state, speculative_state), group in oos.groupby(["market_layer", "speculative_layer"]):
        key = f"{market_state}__{speculative_state}"
        result[key] = {
            f"{horizon}d": core.sample_metrics(group, horizon, screen_config, 9000 + horizon)
            for horizon in (1, 2, 5)
        }
    return result


def run(config: Config) -> dict[str, Any]:
    timing_config = TimingConfig(
        universe=config.universe,
        start=config.start,
        end=config.end,
        oos_start=config.oos_start,
        round_trip_cost=config.round_trip_cost,
        bootstrap_samples=config.bootstrap_samples,
        seed=config.seed,
    )
    frame = add_challenger_features(prepare_timing(timing_config), config.round_trip_cost)
    split = pd.Timestamp(config.oos_start)
    screen_config = core.ScreenConfig(
        universe=config.universe,
        start=config.start,
        end=config.end,
        oos_start=config.oos_start,
        round_trip_cost=config.round_trip_cost,
        bootstrap_samples=config.bootstrap_samples,
        seed=config.seed,
    )
    report: dict[str, Any] = {
        "config": asdict(config),
        "provenance": "external A-share empirical challengers; not trader-personality rules",
        "challengers": {},
        "oos_emotion_layer_quadrants": emotion_quadrants(frame, split, screen_config),
    }
    for index, (name, spec) in enumerate(challenger_masks(frame).items()):
        selected = frame.loc[spec["selected"].fillna(False)]
        control = frame.loc[spec["control"].fillna(False) & ~spec["selected"].fillna(False)]
        item: dict[str, Any] = {
            "meaning": spec["meaning"],
            "expected_direction": spec["direction"],
            "development": {},
            "oos": {},
        }
        for horizon in (1, 2, 5):
            dev_a = selected.loc[selected["date"] < split]
            dev_b = control.loc[control["date"] < split]
            oos_a = selected.loc[selected["date"] >= split]
            oos_b = control.loc[control["date"] >= split]
            item["development"][f"{horizon}d"] = {
                "selected": core.sample_metrics(dev_a, horizon, screen_config, index * 50 + horizon),
                "control": core.sample_metrics(dev_b, horizon, screen_config, index * 50 + horizon + 5),
                "paired": core.paired_difference(dev_a, dev_b, horizon, spec["direction"], screen_config, index * 50 + horizon + 10),
            }
            item["oos"][f"{horizon}d"] = {
                "selected": core.sample_metrics(oos_a, horizon, screen_config, index * 50 + horizon + 20),
                "control": core.sample_metrics(oos_b, horizon, screen_config, index * 50 + horizon + 25),
                "paired": core.paired_difference(oos_a, oos_b, horizon, spec["direction"], screen_config, index * 50 + horizon + 30),
            }
        report["challengers"][name] = item

    output = ROOT / config.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({name: item["oos"]["2d"]["paired"] for name, item in report["challengers"].items()}, ensure_ascii=False, indent=2))
    return report


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="External A-share challenger screen")
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
