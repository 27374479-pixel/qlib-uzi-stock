"""Frozen B01 screen derived from the supplied 48-trader books.

B01 asks a narrow causal question: after a leader has a directly observable
three-board streak, does the *first* non-sealed day have better executable
short-horizon expectancy when it carries the book's participation pattern
(historical-high amount, >=1bn CNY turnover, accessible prior boards)?

The selector and gate are preregistered in
V5_B01_LEADER_DISAGREEMENT_PREREGISTRATION.md.  A pass permits only a later,
separately preregistered minute replay.  No threshold tuning or portfolio
combination is authorized here.
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
PREREG = ROOT / "V5_B01_LEADER_DISAGREEMENT_PREREGISTRATION.md"
OUT = ROOT / "output" / "v5_b01_leader_disagreement"
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
    "version": "V5_B01_LEADER_FIRST_DISAGREEMENT_V1",
    "source": "user-supplied 48-trader books",
    "leader_precursor": "immediately previous trading row sealed with board_height>=3",
    "first_disagreement": "leader precursor followed by current non-sealed row",
    "selected": (
        "first_disagreement AND amount>=prior20_amount_max AND amount>=1bn_CNY "
        "AND prior3_one_word_sum==0"
    ),
    "primary_control": (
        "same first_disagreement, amount>=1bn_CNY, prior3_one_word_sum==0, "
        "but amount<prior20_amount_max"
    ),
    "diagnostic_controls": ["accessibility_control", "turnover_size_control"],
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


def add_b01_features(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.sort_values(["instrument", "date"]).copy()
    by_stock = x.groupby("instrument", sort=False)
    x["prev_board_height"] = by_stock["board_height"].shift(1)
    x["prev_seal_up"] = by_stock["seal_up"].shift(1).fillna(False).astype(bool)
    x["prior20_amount_max"] = by_stock["amount"].transform(
        lambda s: pd.to_numeric(s, errors="coerce").shift(1).rolling(20, min_periods=10).max()
    )
    x["prior3_one_word_sum"] = by_stock["one_word"].transform(
        lambda s: s.fillna(False).astype(float).shift(1).rolling(3, min_periods=3).sum()
    )
    x["first_disagreement"] = (
        x["prev_seal_up"]
        & pd.to_numeric(x["prev_board_height"], errors="coerce").ge(3)
        & ~x["seal_up"].fillna(False).astype(bool)
    )
    amount = pd.to_numeric(x["amount"], errors="coerce")
    x["amount_new_high20"] = x["prior20_amount_max"].notna() & amount.ge(x["prior20_amount_max"])
    x["amount_ge_1bn"] = amount.ge(1_000_000_000.0)
    x["prior3_accessible"] = x["prior3_one_word_sum"].eq(0)
    return x


def b01_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    required = [
        "first_disagreement", "amount_new_high20", "amount_ge_1bn",
        "prior3_accessible", "prior20_amount_max", "prior3_one_word_sum", "amount",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"B01 frame missing required fields: {missing}")

    base = (
        frame["first_disagreement"].fillna(False).astype(bool)
        & frame["prior20_amount_max"].notna()
        & frame["prior3_one_word_sum"].notna()
        & pd.to_datetime(frame["date"]).ge(START)
    )
    amount = pd.to_numeric(frame["amount"], errors="coerce")
    new_high = frame["amount_new_high20"].fillna(False).astype(bool)
    ge_1bn = frame["amount_ge_1bn"].fillna(False).astype(bool)
    accessible = frame["prior3_accessible"].fillna(False).astype(bool)

    selected = base & new_high & ge_1bn & accessible
    volume_control = base & ~new_high & ge_1bn & accessible
    accessibility_control = base & new_high & ge_1bn & frame["prior3_one_word_sum"].ge(1)
    turnover_size_control = base & new_high & ~ge_1bn & accessible & amount.notna()

    masks = {
        "selected": selected,
        "volume_control": volume_control,
        "accessibility_control": accessibility_control,
        "turnover_size_control": turnover_size_control,
    }
    names = list(masks)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            if bool((masks[left] & masks[right]).any()):
                raise RuntimeError(f"B01 cohorts overlap: {left} and {right}")
    return masks


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
            insufficient.append(f"{label}: selected-vs-volume-control paired dates < {MIN_PAIRED_DAYS}")

        mean_return = selected.get("mean_return")
        if mean_return is None or not np.isfinite(mean_return) or float(mean_return) <= 0:
            failures.append(f"{label}: selected 2d mean net return is not positive")
        excess = selected.get("mean_market_excess")
        if excess is None or not np.isfinite(excess) or float(excess) <= 0:
            failures.append(f"{label}: selected 2d mean market excess is not positive")
        diff = paired.get("expected_signed_difference")
        if diff is None or not np.isfinite(diff) or float(diff) <= 0:
            failures.append(f"{label}: selected-minus-volume-control 2d difference is not positive")
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
        reasons = ["all preregistered B01 primary 2d conditions passed"]
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


def regime_diagnostics(selected: pd.DataFrame, config: core.ScreenConfig) -> dict[str, Any]:
    result: dict[str, Any] = {}
    weak = selected["weak_market"].fillna(False).astype(bool)
    for label, mask in (("weak_market", weak), ("non_weak_market", ~weak)):
        sample = selected.loc[mask]
        result[label] = core.sample_metrics(sample, PRIMARY_HORIZON, config, 8100 if label == "weak_market" else 8200)

    yearly: dict[str, Any] = {}
    years = pd.to_datetime(selected["date"]).dt.year
    for year in sorted(years.dropna().unique()):
        sample = selected.loc[years.eq(year)]
        yearly[str(int(year))] = core.sample_metrics(sample, PRIMARY_HORIZON, config, 8300 + int(year) % 100)
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
    return add_b01_features(frame)


def run() -> dict[str, Any]:
    if not PREREG.exists():
        raise FileNotFoundError(PREREG)
    config = screen_config()
    frame = prepare_frame(config)
    masks = b01_masks(frame)
    cohorts = {name: frame.loc[mask].copy() for name, mask in masks.items()}
    selected = cohorts["selected"]
    primary_control = cohorts["volume_control"]

    periods: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    for number, period in enumerate(("development_2021_2023", "historical_later_2024_plus")):
        s = segment_frame(selected, period)
        c = segment_frame(primary_control, period)
        periods[period] = evaluate_pair(s, c, config, 1000 + number * 200)
        diagnostics[period] = {
            "accessibility_control": evaluate_pair(
                s, segment_frame(cohorts["accessibility_control"], period), config, 2000 + number * 200
            ),
            "turnover_size_control": evaluate_pair(
                s, segment_frame(cohorts["turnover_size_control"], period), config, 3000 + number * 200
            ),
            "regime": regime_diagnostics(s, config),
        }

    primary_dev = periods["development_2021_2023"][f"{PRIMARY_HORIZON}d"]
    primary_later = periods["historical_later_2024_plus"][f"{PRIMARY_HORIZON}d"]
    qualification = qualification_from_primary(primary_dev, primary_later)

    OUT.mkdir(parents=True, exist_ok=True)
    observation_columns = [
        "date", "instrument", "entry_date", "entry_filled", "amount", "turnover_rate_pct",
        "board_height", "prev_board_height", "seal_up", "broken_up", "one_word",
        "prior20_amount_max", "prior3_one_word_sum", "first_disagreement",
        "amount_new_high20", "amount_ge_1bn", "weak_market",
        "return_1d", "return_2d", "return_5d",
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
        pd.concat(observations, ignore_index=True).to_parquet(OBSERVATIONS, index=False, compression="zstd")

    counts = {}
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
            "B01 is a one-shot source-grounded daily precursor screen. A pass permits only a separately "
            "preregistered minute replay; a failure is frozen and does not authorize threshold tuning."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "status": qualification["status"],
        "counts": counts,
        "development_2d": primary_dev,
        "historical_later_2d": primary_later,
    }, ensure_ascii=False, indent=2, default=str), flush=True)
    return report


if __name__ == "__main__":
    run()
