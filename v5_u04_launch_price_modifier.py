"""One-shot source-grounded U04 launch-price modifier screen.

The U04 preregistration was committed before any U04 returns were computed.
This module tests the exact <10 CNY source threshold as a *relative modifier*
within accessible three-board starts.  A pass never authorizes a standalone
signal, X02 retuning, portfolio combination, paper trading, or live trading.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import book_alpha_daily_screen as core
import v5_b01_leader_disagreement_screen as b01
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
PREREG = ROOT / "V5_U04_LAUNCH_PRICE_MODIFIER_PREREGISTRATION.md"
OUT = ROOT / "output" / "v5_u04_launch_price_modifier"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "observations.parquet"

START = pd.Timestamp("2021-05-17")
DEV_END = pd.Timestamp("2023-12-31")
LATER_START = pd.Timestamp("2024-01-01")
PRICE_THRESHOLD = 10.0
ROUND_TRIP_COST = 0.0036
BOOTSTRAP_SAMPLES = 5000
SEED = 20260914
PRIMARY_HORIZON = 2
MIN_GROUP_N = 30
MIN_GROUP_DAYS = 20
MIN_PAIRED_DAYS = 15

CONTRACT = {
    "version": "V5_U04_LAUNCH_PRICE_MODIFIER_V1",
    "source": "user-supplied upper 48-trader volume, market-total-leader trait list",
    "source_claims": ["三连板启动", "启动价位低于10元，可炒作空间大"],
    "three_board_start": (
        "current seal_up and board_height==3; T-1 seal_up/board_height==2; "
        "T-2 seal_up/board_height==1"
    ),
    "accessibility": "all three board rows are not one_word",
    "launch_reference_price": "preclose on the first-board row T-2",
    "selected": "launch_reference_price < 10.00 CNY",
    "control": "launch_reference_price >= 10.00 CNY",
    "price_threshold_cny": PRICE_THRESHOLD,
    "entry": "next available open; upper-limit locked next session is unfilled",
    "primary_horizon_trading_days": PRIMARY_HORIZON,
    "diagnostic_horizons_trading_days": [1, 5],
    "round_trip_cost": ROUND_TRIP_COST,
    "bootstrap_samples": BOOTSTRAP_SAMPLES,
    "seed": SEED,
    "qualification_scope": "relative_modifier_only",
    "parameter_search": False,
    "standalone_signal_authorized": False,
    "x02_retuning_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
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
        min_oos_observations=MIN_GROUP_N,
        min_oos_days=MIN_GROUP_DAYS,
        output=str(REPORT.relative_to(ROOT)),
        observations_output=str(OBSERVATIONS.relative_to(ROOT)),
    )


def add_u04_features(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"instrument", "date", "seal_up", "board_height", "one_word", "preclose"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"U04 frame missing required nominal/leader fields: {missing}")

    x = frame.sort_values(["instrument", "date"]).copy()
    g = x.groupby("instrument", sort=False)
    seal = x["seal_up"].fillna(False).astype(bool)
    board = pd.to_numeric(x["board_height"], errors="coerce")
    one_word = x["one_word"].fillna(False).astype(bool)

    x["seal_lag1"] = g["seal_up"].shift(1).fillna(False).astype(bool)
    x["seal_lag2"] = g["seal_up"].shift(2).fillna(False).astype(bool)
    x["board_lag1"] = pd.to_numeric(g["board_height"].shift(1), errors="coerce")
    x["board_lag2"] = pd.to_numeric(g["board_height"].shift(2), errors="coerce")
    x["one_word_lag1"] = g["one_word"].shift(1).fillna(False).astype(bool)
    x["one_word_lag2"] = g["one_word"].shift(2).fillna(False).astype(bool)
    # T-2 is the first-board row.  Its preclose is the nominal close immediately
    # before the three-board sequence began, our frozen launch-price proxy.
    x["launch_reference_price"] = pd.to_numeric(g["preclose"].shift(2), errors="coerce")

    x["three_board_start"] = (
        seal
        & board.eq(3)
        & x["seal_lag1"]
        & x["board_lag1"].eq(2)
        & x["seal_lag2"]
        & x["board_lag2"].eq(1)
    )
    x["three_board_accessible"] = (
        x["three_board_start"]
        & ~one_word
        & ~x["one_word_lag1"]
        & ~x["one_word_lag2"]
    )
    price = x["launch_reference_price"]
    x["valid_launch_reference_price"] = price.notna() & np.isfinite(price) & price.gt(0)
    x["low_launch_price"] = x["valid_launch_reference_price"] & price.lt(PRICE_THRESHOLD)
    return x


def u04_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    required = {
        "date", "three_board_accessible", "valid_launch_reference_price",
        "low_launch_price", "launch_reference_price",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"U04 frame missing derived fields: {missing}")

    base = (
        frame["three_board_accessible"].fillna(False).astype(bool)
        & frame["valid_launch_reference_price"].fillna(False).astype(bool)
        & pd.to_datetime(frame["date"], errors="coerce").ge(START)
    )
    low = frame["low_launch_price"].fillna(False).astype(bool)
    selected = base & low
    control = base & ~low
    if bool((selected & control).any()):
        raise RuntimeError("U04 selected/control cohorts overlap")
    return {"selected_lt10": selected, "control_gte10": control}


def segment(frame: pd.DataFrame, which: str) -> pd.DataFrame:
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if which == "development_2021_2023":
        return frame.loc[dates.between(START, DEV_END)].copy()
    if which == "historical_later_2024_plus":
        return frame.loc[dates.ge(LATER_START)].copy()
    raise ValueError(which)


def evaluate_period(
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
    for label, primary in (
        ("development_2021_2023", development),
        ("historical_later_2024_plus", historical_later),
    ):
        selected = primary.get("selected", {})
        control = primary.get("control", {})
        paired = primary.get("paired", {})
        if int(selected.get("n", 0)) < MIN_GROUP_N:
            insufficient.append(f"{label}: executable <10 launch-price observations < {MIN_GROUP_N}")
        if int(selected.get("active_days", 0)) < MIN_GROUP_DAYS:
            insufficient.append(f"{label}: active <10 launch-price dates < {MIN_GROUP_DAYS}")
        if int(control.get("n", 0)) < MIN_GROUP_N:
            insufficient.append(f"{label}: executable >=10 launch-price observations < {MIN_GROUP_N}")
        if int(control.get("active_days", 0)) < MIN_GROUP_DAYS:
            insufficient.append(f"{label}: active >=10 launch-price dates < {MIN_GROUP_DAYS}")
        if int(paired.get("paired_days", 0)) < MIN_PAIRED_DAYS:
            insufficient.append(f"{label}: paired low/high launch-price dates < {MIN_PAIRED_DAYS}")

        diff = paired.get("expected_signed_difference")
        if diff is None or not np.isfinite(diff) or float(diff) <= 0:
            failures.append(f"{label}: <10 minus >=10 2d paired difference is not positive")
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
        status = "QUALIFIED_AS_RELATIVE_MODIFIER_ONLY"
        reasons = ["all preregistered U04 relative 2d conditions passed"]
    return {
        "status": status,
        "qualified_as_relative_modifier_only": status == "QUALIFIED_AS_RELATIVE_MODIFIER_ONLY",
        "standalone_signal_authorized": False,
        "x02_retuning_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "reasons": reasons,
    }


def _diagnostics(sample: pd.DataFrame, config: core.ScreenConfig, seed_base: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "weak_market" in sample:
        weak = sample["weak_market"].fillna(False).astype(bool)
        result["weak_market_2d"] = core.sample_metrics(sample.loc[weak], 2, config, seed_base + 1)
        result["non_weak_market_2d"] = core.sample_metrics(sample.loc[~weak], 2, config, seed_base + 2)
    years = pd.to_datetime(sample["date"], errors="coerce").dt.year
    result["yearly_2d"] = {
        str(int(year)): core.sample_metrics(
            sample.loc[years.eq(year)], 2, config, seed_base + 100 + int(year) % 100
        )
        for year in sorted(years.dropna().unique())
    }
    return result


def prepare_frame(config: core.ScreenConfig) -> pd.DataFrame:
    # Reuse B01's established point-in-time daily loader and executable forward
    # return labels; U04's selectors use only information known at the third-board close.
    frame = b01.prepare_frame(config)
    return add_u04_features(frame)


def run() -> dict[str, Any]:
    if not PREREG.exists():
        raise FileNotFoundError(PREREG)
    config = screen_config()
    frame = prepare_frame(config)
    masks = u04_masks(frame)
    selected = frame.loc[masks["selected_lt10"]].copy()
    control = frame.loc[masks["control_gte10"]].copy()

    periods: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    for idx, name in enumerate(("development_2021_2023", "historical_later_2024_plus")):
        s = segment(selected, name)
        c = segment(control, name)
        periods[name] = evaluate_period(s, c, config, 1000 + idx * 200)
        diagnostics[name] = {
            "selected_lt10": _diagnostics(s, config, 3000 + idx * 500),
            "control_gte10": _diagnostics(c, config, 4000 + idx * 500),
        }

    primary_dev = periods["development_2021_2023"]["2d"]
    primary_later = periods["historical_later_2024_plus"]["2d"]
    qualification = qualification_from_primary(primary_dev, primary_later)

    OUT.mkdir(parents=True, exist_ok=True)
    keep = [
        "date", "instrument", "entry_date", "entry_filled", "preclose", "close",
        "board_height", "one_word", "launch_reference_price", "three_board_start",
        "three_board_accessible", "low_launch_price", "weak_market",
        "return_1d", "return_2d", "return_5d",
        "market_excess_1d", "market_excess_2d", "market_excess_5d",
    ]
    keep = [c for c in keep if c in frame.columns]
    obs: list[pd.DataFrame] = []
    for cohort_name, cohort in (("selected_lt10", selected), ("control_gte10", control)):
        if cohort.empty:
            continue
        item = cohort[keep].copy()
        item["cohort"] = cohort_name
        obs.append(item)
    if obs:
        pd.concat(obs, ignore_index=True).to_parquet(OBSERVATIONS, index=False, compression="zstd")

    def count(sample: pd.DataFrame) -> dict[str, Any]:
        filled = sample["entry_filled"].fillna(False).astype(bool)
        return {
            "signals": int(len(sample)),
            "active_dates": int(sample["date"].nunique()),
            "executable": int(filled.sum()),
            "executable_active_dates": int(sample.loc[filled, "date"].nunique()),
            "fill_rate": float(filled.mean()) if len(sample) else None,
        }

    report = {
        "contract": CONTRACT,
        "preregistration_sha256": sha256_file(PREREG),
        "counts": {
            "selected_lt10": count(selected),
            "control_gte10": count(control),
        },
        "periods": periods,
        "diagnostics": diagnostics,
        "primary_qualification": qualification,
        "interpretation_boundary": (
            "U04 tests only whether the exact book-stated <10 CNY launch-price characteristic is a "
            "relative modifier within the frozen accessible three-board-start population. A pass is not "
            "standalone alpha authorization; a failure/insufficient result cannot be rescued by changing "
            "the price threshold, launch-price definition, board count, accessibility base, horizon or cost."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "status": qualification["status"],
        "counts": report["counts"],
        "development_2d": primary_dev,
        "historical_later_2d": primary_later,
    }, ensure_ascii=False, indent=2, default=str), flush=True)
    return report


if __name__ == "__main__":
    run()
