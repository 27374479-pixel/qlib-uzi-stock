"""Preregistered D01 defensive low-volatility trend sleeve screen.

The exact selector, control, costs, horizons and qualification rule are frozen in
V5_DEFENSIVE_SLEEVE_PREREGISTRATION.md before this script's first result is
read.  A pass only permits a later minute-level execution replay; it does not
permit portfolio combination or live trading.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import book_alpha_daily_screen as core
import external_challenger_daily_screen as challenger
from attention_timing_decomposition import Config as TimingConfig, prepare as prepare_timing
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
PREREG = ROOT / "V5_DEFENSIVE_SLEEVE_PREREGISTRATION.md"
OUT = ROOT / "output" / "v5_defensive_sleeve_d01"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "observations.parquet"

START = pd.Timestamp("2021-05-17")
SPLIT = pd.Timestamp("2024-01-01")
DEV_END = pd.Timestamp("2023-12-31")
ROUND_TRIP_COST = 0.0036
BOOTSTRAP_SAMPLES = 5000
SEED = 20260914
PRIMARY_HORIZON = 5

CONTRACT = {
    "version": "V5_DEFENSIVE_SLEEVE_D01_SCREEN_V1",
    "mechanism": "positive clean 60d trend plus low realized 20d volatility",
    "universe": "point-in-time CSI800 with existing listing/ST/tradability policy",
    "signal_timing": "completed signal-date daily state only",
    "entry": "next available open; locked upper-limit next session is unfilled",
    "primary_horizon_trading_days": PRIMARY_HORIZON,
    "diagnostic_horizons_trading_days": [1, 2],
    "round_trip_cost": ROUND_TRIP_COST,
    "selected": "clean_mom60>0, clean_mom60_rank>=0.70, hit_count20<=1, vol20_rank<=0.35",
    "control": "same trend requirements but vol20_rank>=0.65",
    "parameter_search": False,
    "x02_retuning": False,
    "portfolio_combination_authorized": False,
    "live_trading_authorized": False,
}


def add_d01_features(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.sort_values(["instrument", "date"]).copy()
    x["daily_ret"] = pd.to_numeric(x["close"], errors="coerce") / pd.to_numeric(x["preclose"], errors="coerce") - 1.0
    by_stock = x.groupby("instrument", sort=False)
    x["vol20"] = by_stock["daily_ret"].transform(lambda s: s.rolling(20, min_periods=15).std(ddof=1))
    x["vol20_rank"] = x.groupby("date")["vol20"].rank(pct=True)
    # The shared challenger layer computes clean_mom60 itself but only exposes a
    # rank for the 20-day variant. D01 preregistered a cross-sectional 60-day
    # rank, so derive that exact rank here without changing any threshold.
    x["clean_mom60_rank"] = x.groupby("date")["clean_mom60"].rank(pct=True)
    return x


def d01_masks(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    required = [
        "date", "clean_mom60", "clean_mom60_rank", "hit_count20", "vol20_rank", "entry_filled",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"D01 frame missing required fields: {missing}")
    common = (
        pd.to_datetime(frame["date"]).ge(START)
        & pd.to_numeric(frame["clean_mom60"], errors="coerce").gt(0)
        & pd.to_numeric(frame["clean_mom60_rank"], errors="coerce").ge(0.70)
        & pd.to_numeric(frame["hit_count20"], errors="coerce").le(1)
        & pd.to_numeric(frame["vol20_rank"], errors="coerce").notna()
        & frame["entry_filled"].fillna(False).astype(bool)
    )
    selected = common & pd.to_numeric(frame["vol20_rank"], errors="coerce").le(0.35)
    control = common & pd.to_numeric(frame["vol20_rank"], errors="coerce").ge(0.65)
    if bool((selected & control).any()):
        raise RuntimeError("D01 selected and control cohorts overlap")
    return selected, control


def _screen_config() -> core.ScreenConfig:
    return core.ScreenConfig(
        universe="csi800",
        start="2015-01-01",
        end="2026-09-03",
        oos_start=str(SPLIT.date()),
        round_trip_cost=ROUND_TRIP_COST,
        bootstrap_samples=BOOTSTRAP_SAMPLES,
        seed=SEED,
        min_oos_observations=100,
        min_oos_days=40,
        output=str(REPORT.relative_to(ROOT)),
        observations_output=str(OBSERVATIONS.relative_to(ROOT)),
    )


def evaluate_segment(selected: pd.DataFrame, control: pd.DataFrame, horizon: int, config: core.ScreenConfig, seed_offset: int) -> dict[str, Any]:
    return {
        "selected": core.sample_metrics(selected, horizon, config, seed_offset),
        "control": core.sample_metrics(control, horizon, config, seed_offset + 5),
        "paired": core.paired_difference(selected, control, horizon, 1, config, seed_offset + 10),
    }


def qualification_from_primary(development: dict[str, Any], later: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    for label, segment in (("development_2021_2023", development), ("historical_later_2024_plus", later)):
        selected = segment.get("selected", {})
        paired = segment.get("paired", {})
        if int(selected.get("n", 0)) < 100:
            reasons.append(f"{label}: selected observations < 100")
        if int(selected.get("active_days", 0)) < 40:
            reasons.append(f"{label}: active signal dates < 40")
        mean_return = selected.get("mean_return")
        if mean_return is None or not np.isfinite(mean_return) or float(mean_return) <= 0:
            reasons.append(f"{label}: selected mean return is not positive")
        excess = selected.get("mean_market_excess")
        if excess is None or not np.isfinite(excess) or float(excess) <= 0:
            reasons.append(f"{label}: selected mean market excess is not positive")
        diff = paired.get("selected_minus_control")
        if diff is None or not np.isfinite(diff) or float(diff) <= 0:
            reasons.append(f"{label}: paired selected-minus-control is not positive")
        ci = paired.get("bootstrap95_expected_signed_difference") or [None, None]
        lower = ci[0] if len(ci) else None
        if lower is None or not np.isfinite(lower) or float(lower) <= 0:
            reasons.append(f"{label}: paired bootstrap 95% lower bound is not above zero")
    return {
        "status": "QUALIFIED_FOR_MINUTE_REPLAY" if not reasons else "REJECTED",
        "qualified_for_minute_replay": not reasons,
        "portfolio_combination_authorized": False,
        "live_trading_authorized": False,
        "reasons": reasons or ["all preregistered D01 5-day qualification conditions passed"],
    }


def build_frame(config: core.ScreenConfig) -> pd.DataFrame:
    timing = TimingConfig(
        universe=config.universe,
        start=config.start,
        end=config.end,
        oos_start=config.oos_start,
        round_trip_cost=config.round_trip_cost,
        bootstrap_samples=config.bootstrap_samples,
        seed=config.seed,
    )
    # prepare_timing enforces the existing true-listing policy and creates a
    # causal next-open fill flag. challenger features add clean_mom60 and fixed
    # forward returns after the preregistered cost.
    frame = challenger.add_challenger_features(prepare_timing(timing), config.round_trip_cost)
    return add_d01_features(frame)


def run() -> dict[str, Any]:
    if not PREREG.exists():
        raise FileNotFoundError(PREREG)
    config = _screen_config()
    frame = build_frame(config)
    selected_mask, control_mask = d01_masks(frame)
    selected = frame.loc[selected_mask].copy()
    control = frame.loc[control_mask].copy()

    dev_selected = selected[(selected["date"] >= START) & (selected["date"] <= DEV_END)]
    dev_control = control[(control["date"] >= START) & (control["date"] <= DEV_END)]
    later_selected = selected[selected["date"] >= SPLIT]
    later_control = control[control["date"] >= SPLIT]

    periods: dict[str, Any] = {
        "development_2021_2023": {},
        "historical_later_2024_plus": {},
    }
    for horizon in (1, 2, 5):
        periods["development_2021_2023"][f"{horizon}d"] = evaluate_segment(
            dev_selected, dev_control, horizon, config, 100 * horizon
        )
        periods["historical_later_2024_plus"][f"{horizon}d"] = evaluate_segment(
            later_selected, later_control, horizon, config, 100 * horizon + 50
        )

    primary_dev = periods["development_2021_2023"]["5d"]
    primary_later = periods["historical_later_2024_plus"]["5d"]
    qualification = qualification_from_primary(primary_dev, primary_later)

    OUT.mkdir(parents=True, exist_ok=True)
    observation_columns = [
        "date", "instrument", "entry_date", "entry_filled", "clean_mom60", "clean_mom60_rank",
        "hit_count20", "vol20", "vol20_rank", "return_1d", "return_2d", "return_5d",
        "market_excess_1d", "market_excess_2d", "market_excess_5d",
    ]
    selected_obs = selected[observation_columns].copy()
    selected_obs["cohort"] = "selected_low_vol"
    control_obs = control[observation_columns].copy()
    control_obs["cohort"] = "control_high_vol"
    pd.concat([selected_obs, control_obs], ignore_index=True).to_parquet(OBSERVATIONS, index=False, compression="zstd")

    report = {
        "contract": CONTRACT,
        "preregistration_sha256": sha256_file(PREREG),
        "config": asdict(config),
        "periods": periods,
        "primary_qualification": qualification,
        "counts": {
            "selected_total": int(len(selected)),
            "control_total": int(len(control)),
            "selected_development": int(len(dev_selected)),
            "selected_later": int(len(later_selected)),
        },
        "interpretation_boundary": (
            "D01 is a one-shot historical sleeve qualification screen. A pass only permits a separately preregistered minute replay; "
            "a failure freezes D01 as rejected and does not authorize threshold tuning."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str), flush=True)
    return report


if __name__ == "__main__":
    run()
