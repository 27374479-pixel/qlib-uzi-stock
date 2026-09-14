"""Frozen B02 screen derived from the supplied 48-trader books.

The source explicitly names market-total-leader tactics including 龙头首阴 and
龙回头. B02 tests the minimal daily precursor without importing B01's amount,
turnover, accessibility, price, sector, or regime filters.

Signal T is known only after close T. Entry is next available open. The fixed
primary question is whether a first bearish non-sealed day immediately after a
point-in-time market-leading sealed streak has positive 2-day executable
expectancy and beats same-date first-yin events from lower-height streaks.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import book_alpha_daily_screen as core
from attention_timing_decomposition import Config as TimingConfig, prepare as prepare_timing
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
PREREG = ROOT / "V5_B02_LEADER_FIRST_YIN_PREREGISTRATION.md"
OUT = ROOT / "output" / "v5_b02_leader_first_yin"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "observations.parquet"

START = pd.Timestamp("2021-05-17")
DEV_END = pd.Timestamp("2023-12-31")
LATER_START = pd.Timestamp("2024-01-01")
ROUND_TRIP_COST = 0.0036
BOOTSTRAP_SAMPLES = 5000
SEED = 20260914
PRIMARY_HORIZON = 2
MIN_SELECTED_N = 30
MIN_ACTIVE_DAYS = 20
MIN_PAIRED_DAYS = 15

CONTRACT = {
    "version": "V5_B02_MARKET_LEADER_FIRST_YIN_V1",
    "source": "user-supplied 48-trader books: market total leader -> leader first-yin / dragon-return tactics",
    "leader_proxy": (
        "on T-1, stock is sealed and its consecutive board_height equals the point-in-time "
        "CSI800 market maximum board_height; ties allowed"
    ),
    "first_yin": "immediately next trading row T is non-sealed and ret1<0",
    "selected": "first_yin AND prev_board_height==prev_market_max_board_height AND prev_board_height>0",
    "primary_control": "same first_yin event but 0<prev_board_height<prev_market_max_board_height",
    "excluded_from_eligibility": [
        "amount", "turnover", "price", "prior_one_word_history", "industry", "market_regime", "X02"
    ],
    "entry": "next available open; upper-limit locked next session is unfilled",
    "primary_horizon_trading_days": PRIMARY_HORIZON,
    "diagnostic_horizons_trading_days": [1, 5],
    "round_trip_cost": ROUND_TRIP_COST,
    "bootstrap_samples": BOOTSTRAP_SAMPLES,
    "seed": SEED,
    "parameter_search": False,
    "x02_retuning": False,
    "portfolio_combination_authorized": False,
    "live_trading_authorized": False,
}


def screen_config() -> core.ScreenConfig:
    return core.ScreenConfig(
        universe="csi800",
        start="2015-01-01",
        end="2026-09-03",
        oos_start=str(LATER_START.date()),
        round_trip_cost=ROUND_TRIP_COST,
        bootstrap_samples=BOOTSTRAP_SAMPLES,
        seed=SEED,
        min_oos_observations=MIN_SELECTED_N,
        min_oos_days=MIN_ACTIVE_DAYS,
        output=str(REPORT.relative_to(ROOT)),
        observations_output=str(OBSERVATIONS.relative_to(ROOT)),
    )


def add_b02_features(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.sort_values(["instrument", "date"]).copy()
    x["date"] = pd.to_datetime(x["date"])

    # Market leadership is defined cross-sectionally at each completed close,
    # avoiding any ex-post winner label or optimized absolute board threshold.
    market_max = (
        x.groupby("date", sort=True)["board_height"]
        .max()
        .astype(float)
        .rename("market_max_board_height")
    )
    x["market_max_board_height"] = x["date"].map(market_max)

    by_stock = x.groupby("instrument", sort=False)
    x["prev_date"] = by_stock["date"].shift(1)
    x["prev_board_height"] = pd.to_numeric(by_stock["board_height"].shift(1), errors="coerce")
    x["prev_seal_up"] = by_stock["seal_up"].shift(1).fillna(False).astype(bool)
    x["prev_one_word"] = by_stock["one_word"].shift(1).fillna(False).astype(bool)
    x["prev_market_max_board_height"] = x["prev_date"].map(market_max)

    current_negative = pd.to_numeric(x["ret1"], errors="coerce").lt(0)
    current_nonsealed = ~x["seal_up"].fillna(False).astype(bool)
    x["first_yin_after_streak"] = (
        x["prev_seal_up"]
        & x["prev_board_height"].gt(0)
        & current_nonsealed
        & current_negative
    )
    x["was_market_leader"] = (
        x["prev_market_max_board_height"].notna()
        & x["prev_board_height"].eq(x["prev_market_max_board_height"])
        & x["prev_board_height"].gt(0)
    )
    x["was_lower_height_streak"] = (
        x["prev_market_max_board_height"].notna()
        & x["prev_board_height"].gt(0)
        & x["prev_board_height"].lt(x["prev_market_max_board_height"])
    )
    return x


def b02_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    required = [
        "first_yin_after_streak", "was_market_leader", "was_lower_height_streak",
        "prev_board_height", "prev_market_max_board_height", "date",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"B02 frame missing required fields: {missing}")

    in_window = pd.to_datetime(frame["date"]).ge(START)
    event = frame["first_yin_after_streak"].fillna(False).astype(bool) & in_window
    selected = event & frame["was_market_leader"].fillna(False).astype(bool)
    control = event & frame["was_lower_height_streak"].fillna(False).astype(bool)
    if bool((selected & control).any()):
        raise RuntimeError("B02 selected/control cohorts overlap")
    return {"selected": selected, "lower_height_control": control}


def evaluate_pair(
    selected: pd.DataFrame,
    control: pd.DataFrame,
    config: core.ScreenConfig,
    seed_offset: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in (1, 2, 5):
        result[f"{horizon}d"] = {
            "selected": core.sample_metrics(selected, horizon, config, seed_offset + horizon),
            "control": core.sample_metrics(control, horizon, config, seed_offset + horizon + 10),
            "paired": core.paired_difference(
                selected, control, horizon, 1, config, seed_offset + horizon + 20
            ),
        }
    return result


def qualification_from_primary(
    development: dict[str, Any], historical_later: dict[str, Any]
) -> dict[str, Any]:
    insufficient: list[str] = []
    failures: list[str] = []
    for label, segment in (
        ("development_2021_2023", development),
        ("historical_later_2024_plus", historical_later),
    ):
        selected = segment.get("selected", {})
        paired = segment.get("paired", {})
        if int(selected.get("n", 0)) < MIN_SELECTED_N:
            insufficient.append(f"{label}: selected executable observations < {MIN_SELECTED_N}")
        if int(selected.get("active_days", 0)) < MIN_ACTIVE_DAYS:
            insufficient.append(f"{label}: selected active dates < {MIN_ACTIVE_DAYS}")
        if int(paired.get("paired_days", 0)) < MIN_PAIRED_DAYS:
            insufficient.append(f"{label}: same-date selected-vs-control paired dates < {MIN_PAIRED_DAYS}")

        mean_return = selected.get("mean_return")
        if mean_return is None or not np.isfinite(mean_return) or float(mean_return) <= 0:
            failures.append(f"{label}: selected 2d mean net return is not positive")
        excess = selected.get("mean_market_excess")
        if excess is None or not np.isfinite(excess) or float(excess) <= 0:
            failures.append(f"{label}: selected 2d mean market excess is not positive")
        diff = paired.get("expected_signed_difference")
        if diff is None or not np.isfinite(diff) or float(diff) <= 0:
            failures.append(f"{label}: selected-minus-control 2d difference is not positive")
        ci = paired.get("bootstrap95_expected_signed_difference") or [None, None]
        lower = ci[0] if len(ci) else None
        if lower is None or not np.isfinite(lower) or float(lower) <= 0:
            failures.append(f"{label}: paired 2d bootstrap 95% lower bound is not above zero")

    if insufficient:
        status = "INSUFFICIENT"
        reasons = insufficient + failures
    elif failures:
        status = "REJECTED"
        reasons = failures
    else:
        status = "QUALIFIED_FOR_MINUTE_REPLAY"
        reasons = ["all preregistered B02 primary 2d conditions passed"]
    return {
        "status": status,
        "qualified_for_minute_replay": status == "QUALIFIED_FOR_MINUTE_REPLAY",
        "portfolio_combination_authorized": False,
        "live_trading_authorized": False,
        "reasons": reasons,
    }


def segment_frame(frame: pd.DataFrame, which: str) -> pd.DataFrame:
    dates = pd.to_datetime(frame["date"])
    if which == "development_2021_2023":
        return frame.loc[dates.between(START, DEV_END)]
    if which == "historical_later_2024_plus":
        return frame.loc[dates.ge(LATER_START)]
    raise ValueError(which)


def selected_diagnostics(selected: pd.DataFrame, config: core.ScreenConfig) -> dict[str, Any]:
    result: dict[str, Any] = {}
    weak = selected["weak_market"].fillna(False).astype(bool)
    result["market_regime"] = {
        "weak_market": core.sample_metrics(selected.loc[weak], PRIMARY_HORIZON, config, 8101),
        "non_weak_market": core.sample_metrics(selected.loc[~weak], PRIMARY_HORIZON, config, 8102),
    }

    current_ret = pd.to_numeric(selected["ret1"], errors="coerce")
    result["first_yin_severity"] = {}
    for label, mask in (
        ("mild_0_to_minus3pct", current_ret.gt(-0.03) & current_ret.lt(0)),
        ("medium_minus3_to_minus7pct", current_ret.le(-0.03) & current_ret.gt(-0.07)),
        ("deep_le_minus7pct", current_ret.le(-0.07)),
    ):
        result["first_yin_severity"][label] = core.sample_metrics(
            selected.loc[mask], PRIMARY_HORIZON, config, 8200 + len(result["first_yin_severity"])
        )

    result["prior_board_accessibility"] = {
        "prev_one_word": core.sample_metrics(
            selected.loc[selected["prev_one_word"].fillna(False).astype(bool)], PRIMARY_HORIZON, config, 8301
        ),
        "prev_not_one_word": core.sample_metrics(
            selected.loc[~selected["prev_one_word"].fillna(False).astype(bool)], PRIMARY_HORIZON, config, 8302
        ),
    }

    yearly: dict[str, Any] = {}
    years = pd.to_datetime(selected["date"]).dt.year
    for year in sorted(years.dropna().unique()):
        yearly[str(int(year))] = core.sample_metrics(
            selected.loc[years.eq(year)], PRIMARY_HORIZON, config, 8400 + int(year) % 100
        )
    result["yearly"] = yearly
    return result


def prepare_frame(config: core.ScreenConfig) -> pd.DataFrame:
    timing = TimingConfig(
        universe=config.universe,
        start=config.start,
        end=config.end,
        oos_start=config.oos_start,
        round_trip_cost=config.round_trip_cost,
        bootstrap_samples=config.bootstrap_samples,
        seed=config.seed,
    )
    frame = prepare_timing(timing)
    frame = core.attach_forward_returns(frame, config.round_trip_cost)
    return add_b02_features(frame)


def run() -> dict[str, Any]:
    if not PREREG.exists():
        raise FileNotFoundError(PREREG)
    config = screen_config()
    frame = prepare_frame(config)
    masks = b02_masks(frame)
    cohorts = {name: frame.loc[mask].copy() for name, mask in masks.items()}
    selected = cohorts["selected"]
    control = cohorts["lower_height_control"]

    periods: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    for number, period in enumerate(("development_2021_2023", "historical_later_2024_plus")):
        s = segment_frame(selected, period)
        c = segment_frame(control, period)
        periods[period] = evaluate_pair(s, c, config, 1000 + number * 200)
        diagnostics[period] = selected_diagnostics(s, config)

    primary_dev = periods["development_2021_2023"][f"{PRIMARY_HORIZON}d"]
    primary_later = periods["historical_later_2024_plus"][f"{PRIMARY_HORIZON}d"]
    qualification = qualification_from_primary(primary_dev, primary_later)

    OUT.mkdir(parents=True, exist_ok=True)
    observation_columns = [
        "date", "instrument", "entry_date", "entry_filled", "ret1", "amount",
        "turnover_rate_pct", "board_height", "seal_up", "one_word", "weak_market",
        "prev_date", "prev_board_height", "prev_market_max_board_height", "prev_seal_up",
        "prev_one_word", "first_yin_after_streak", "was_market_leader",
        "was_lower_height_streak", "return_1d", "return_2d", "return_5d",
        "market_excess_1d", "market_excess_2d", "market_excess_5d",
    ]
    observations: list[pd.DataFrame] = []
    for name, cohort in cohorts.items():
        if cohort.empty:
            continue
        item = cohort[observation_columns].copy()
        item["cohort"] = name
        observations.append(item)
    if observations:
        pd.concat(observations, ignore_index=True).to_parquet(
            OBSERVATIONS, index=False, compression="zstd"
        )

    counts: dict[str, Any] = {}
    for name, cohort in cohorts.items():
        executable = cohort["entry_filled"].fillna(False).astype(bool)
        counts[name] = {
            "signals": int(len(cohort)),
            "active_dates": int(cohort["date"].nunique()),
            "executable": int(executable.sum()),
            "fill_rate": float(executable.mean()) if len(cohort) else None,
        }

    report = {
        "contract": CONTRACT,
        "preregistration_sha256": sha256_file(PREREG),
        "config": asdict(config),
        "counts": counts,
        "periods": periods,
        "diagnostics": diagnostics,
        "primary_qualification": qualification,
        "interpretation_boundary": (
            "B02 tests only the book-named market-leader first-yin precursor. Diagnostics do not modify "
            "eligibility. A pass permits only a separately preregistered minute reclaim/execution study; "
            "a failure is frozen and does not authorize threshold tuning."
        ),
    }
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({
        "status": qualification["status"],
        "counts": counts,
        "development_2d": primary_dev,
        "historical_later_2d": primary_later,
    }, ensure_ascii=False, indent=2, default=str), flush=True)
    return report


if __name__ == "__main__":
    run()
