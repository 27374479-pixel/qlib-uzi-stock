"""Frozen K01 audit of the supplied-book 20-day MA downward veto."""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import book_alpha_daily_screen as core
import v5_b01_leader_disagreement_screen as b01
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
PREREG = ROOT / "V5_K01_BOOK_MA20_VETO_PREREGISTRATION.md"
OUT = ROOT / "output" / "v5_k01_book_ma20_veto"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "observations.parquet"
START = pd.Timestamp("2021-05-17")
DEV_END = pd.Timestamp("2023-12-31")
LATER_START = pd.Timestamp("2024-01-01")
PRIMARY_HORIZON = 2
MIN_N = 1000
MIN_ACTIVE_DAYS = 200
MIN_PAIRED_DAYS = 200

CONTRACT = {
    "version": "V5_K01_BOOK_MA20_DIRECTION_VETO_V1",
    "source": "user-supplied lower 48-trader volume: 20-day MA direction downward -> do not participate",
    "ma20": "arithmetic mean of current and prior 19 closes, using completed close T only",
    "selected": "MA20_T >= MA20_T-1",
    "control": "MA20_T < MA20_T-1",
    "primary_horizon_days": PRIMARY_HORIZON,
    "round_trip_cost": b01.ROUND_TRIP_COST,
    "bootstrap_samples": b01.BOOTSTRAP_SAMPLES,
    "seed": b01.SEED,
    "parameter_search": False,
    "retrofit_prior_experiments": False,
    "portfolio_combination_authorized": False,
    "live_trading_authorized": False,
}


def screen_config() -> core.ScreenConfig:
    return replace(
        b01.screen_config(),
        output=str(REPORT.relative_to(ROOT)),
        observations_output=str(OBSERVATIONS.relative_to(ROOT)),
    )


def add_ma20_direction(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.sort_values(["instrument", "date"]).copy()
    close = pd.to_numeric(x["close"], errors="coerce")
    x["_close"] = close
    by_stock = x.groupby("instrument", sort=False)
    x["ma20"] = by_stock["_close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    x["ma20_prev"] = by_stock["ma20"].shift(1)
    x["ma20_valid"] = x["ma20"].notna() & x["ma20_prev"].notna()
    x["ma20_down"] = x["ma20_valid"] & x["ma20"].lt(x["ma20_prev"])
    x["ma20_non_down"] = x["ma20_valid"] & ~x["ma20_down"]
    return x.drop(columns=["_close"])


def segment(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    dates = pd.to_datetime(frame["date"])
    if name == "development_2021_2023":
        return frame.loc[dates.between(START, DEV_END)]
    if name == "historical_later_2024_plus":
        return frame.loc[dates.ge(LATER_START)]
    raise ValueError(name)


def evaluate(selected: pd.DataFrame, control: pd.DataFrame, config: core.ScreenConfig, seed: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in (1, 2, 5):
        result[f"{horizon}d"] = {
            "selected": core.sample_metrics(selected, horizon, config, seed + horizon),
            "control": core.sample_metrics(control, horizon, config, seed + 10 + horizon),
            "paired": core.paired_difference(selected, control, horizon, 1, config, seed + 20 + horizon),
        }
    return result


def qualification(dev: dict[str, Any], later: dict[str, Any]) -> dict[str, Any]:
    insufficient: list[str] = []
    failures: list[str] = []
    for label, block in (("development_2021_2023", dev), ("historical_later_2024_plus", later)):
        selected = block.get("selected", {})
        control = block.get("control", {})
        paired = block.get("paired", {})
        if int(selected.get("n", 0)) < MIN_N:
            insufficient.append(f"{label}: non-downward executable observations < {MIN_N}")
        if int(control.get("n", 0)) < MIN_N:
            insufficient.append(f"{label}: downward executable observations < {MIN_N}")
        if int(selected.get("active_days", 0)) < MIN_ACTIVE_DAYS:
            insufficient.append(f"{label}: non-downward active dates < {MIN_ACTIVE_DAYS}")
        if int(control.get("active_days", 0)) < MIN_ACTIVE_DAYS:
            insufficient.append(f"{label}: downward active dates < {MIN_ACTIVE_DAYS}")
        if int(paired.get("paired_days", 0)) < MIN_PAIRED_DAYS:
            insufficient.append(f"{label}: paired dates < {MIN_PAIRED_DAYS}")

        diff = paired.get("expected_signed_difference")
        ci = paired.get("bootstrap95_expected_signed_difference") or [None, None]
        lower = ci[0] if ci else None
        control_excess = control.get("mean_market_excess")
        if diff is None or not np.isfinite(diff) or float(diff) <= 0:
            failures.append(f"{label}: non-downward-minus-downward 2d paired difference is not positive")
        if lower is None or not np.isfinite(lower) or float(lower) <= 0:
            failures.append(f"{label}: paired 2d bootstrap 95% lower bound is not above zero")
        if control_excess is None or not np.isfinite(control_excess) or float(control_excess) >= 0:
            failures.append(f"{label}: downward-MA20 2d mean market excess is not negative")

    if insufficient:
        status = "INSUFFICIENT"
        reasons = insufficient + failures
    elif failures:
        status = "NOT_VALIDATED"
        reasons = failures
    else:
        status = "VALIDATED_AS_RISK_VETO"
        reasons = ["all preregistered K01 2d risk-veto conditions passed in both historical segments"]
    return {
        "status": status,
        "validated_as_risk_veto": status == "VALIDATED_AS_RISK_VETO",
        "retrofit_prior_experiments": False,
        "portfolio_combination_authorized": False,
        "live_trading_authorized": False,
        "reasons": reasons,
    }


def run() -> dict[str, Any]:
    if not PREREG.exists():
        raise FileNotFoundError(PREREG)
    config = screen_config()
    frame = add_ma20_direction(b01.prepare_frame(config))
    eligible = frame.loc[pd.to_datetime(frame["date"]).ge(START) & frame["ma20_valid"]].copy()
    selected = eligible.loc[eligible["ma20_non_down"]].copy()
    control = eligible.loc[eligible["ma20_down"]].copy()

    periods: dict[str, Any] = {}
    for i, name in enumerate(("development_2021_2023", "historical_later_2024_plus")):
        periods[name] = evaluate(segment(selected, name), segment(control, name), config, 9000 + i * 200)
    dev = periods["development_2021_2023"]["2d"]
    later = periods["historical_later_2024_plus"]["2d"]
    gate = qualification(dev, later)

    OUT.mkdir(parents=True, exist_ok=True)
    cols = [
        "date", "instrument", "entry_date", "entry_filled", "close", "ma20", "ma20_prev",
        "ma20_down", "return_1d", "return_2d", "return_5d",
        "market_excess_1d", "market_excess_2d", "market_excess_5d",
    ]
    obs = []
    for name, cohort in (("non_downward", selected), ("downward", control)):
        item = cohort[cols].copy()
        item["cohort"] = name
        obs.append(item)
    pd.concat(obs, ignore_index=True).to_parquet(OBSERVATIONS, index=False, compression="zstd")

    report = {
        "contract": CONTRACT,
        "preregistration_sha256": sha256_file(PREREG),
        "config": asdict(config),
        "counts": {
            "non_downward": {"rows": int(len(selected)), "active_dates": int(selected["date"].nunique())},
            "downward": {"rows": int(len(control)), "active_dates": int(control["date"].nunique())},
        },
        "periods": periods,
        "primary_qualification": gate,
        "interpretation_boundary": (
            "K01 validates only a generic book-grounded risk veto. It cannot retrofit X02/B01/B02/B03 or authorize a strategy."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": gate["status"], "development_2d": dev, "historical_later_2d": later}, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
