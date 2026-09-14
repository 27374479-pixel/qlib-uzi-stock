"""Frozen B03 historical screen for the book-named leader second-wave pattern."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import book_alpha_daily_screen as core
import v5_b01_leader_disagreement_screen as b01
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
PREREG = ROOT / "V5_B03_LEADER_SECOND_WAVE_PREREGISTRATION.md"
OUT = ROOT / "output" / "v5_b03_leader_second_wave"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "observations.parquet"
START = pd.Timestamp("2021-05-17")
DEV_END = pd.Timestamp("2023-12-31")
LATER_START = pd.Timestamp("2024-01-01")
PRIMARY_HORIZON = 2

CONTRACT = {
    "version": "V5_B03_MARKET_LEADER_SECOND_WAVE_V1",
    "source": "user-supplied 48-trader books: 龙头二波/龙回头 and nearby 总龙头退潮两三天 wording",
    "selected": "market-max sealed leader -> exactly 2 or 3 non-sealed sessions -> first reseal",
    "control": "same interruption/reseal structure after a lower-than-market-max sealed streak",
    "primary_horizon_days": 2,
    "round_trip_cost": b01.ROUND_TRIP_COST,
    "parameter_search": False,
}


def add_b03_features(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.sort_values(["instrument", "date"]).copy()
    x["market_max_board_height"] = x.groupby("date")["board_height"].transform("max")
    g = x.groupby("instrument", sort=False)
    for lag in range(1, 5):
        x[f"seal_lag{lag}"] = g["seal_up"].shift(lag).fillna(False).astype(bool)
        x[f"board_lag{lag}"] = pd.to_numeric(g["board_height"].shift(lag), errors="coerce")
        x[f"max_lag{lag}"] = pd.to_numeric(g["market_max_board_height"].shift(lag), errors="coerce")
    seal = x["seal_up"].fillna(False).astype(bool)
    gap2 = seal & ~x["seal_lag1"] & ~x["seal_lag2"] & x["seal_lag3"]
    gap3 = seal & ~x["seal_lag1"] & ~x["seal_lag2"] & ~x["seal_lag3"] & x["seal_lag4"]
    x["second_wave_restart"] = gap2 | gap3
    x["gap_sessions"] = np.select([gap2, gap3], [2, 3], default=0).astype(int)
    x["peak_board_height"] = np.where(gap2, x["board_lag3"], np.where(gap3, x["board_lag4"], np.nan))
    x["peak_market_max"] = np.where(gap2, x["max_lag3"], np.where(gap3, x["max_lag4"], np.nan))
    x["peak_was_market_leader"] = (
        x["second_wave_restart"]
        & pd.to_numeric(x["peak_board_height"], errors="coerce").gt(0)
        & pd.to_numeric(x["peak_board_height"], errors="coerce").eq(pd.to_numeric(x["peak_market_max"], errors="coerce"))
    )
    return x


def b03_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    dates = pd.to_datetime(frame["date"])
    base = frame["second_wave_restart"].fillna(False).astype(bool) & dates.ge(START)
    peak = pd.to_numeric(frame["peak_board_height"], errors="coerce")
    maxh = pd.to_numeric(frame["peak_market_max"], errors="coerce")
    selected = base & frame["peak_was_market_leader"].fillna(False).astype(bool)
    control = base & peak.gt(0) & maxh.gt(peak)
    if bool((selected & control).any()):
        raise RuntimeError("B03 cohorts overlap")
    return {"selected": selected, "lower_height_control": control}


def segment(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    dates = pd.to_datetime(frame["date"])
    if name == "development_2021_2023":
        return frame.loc[dates.between(START, DEV_END)]
    if name == "historical_later_2024_plus":
        return frame.loc[dates.ge(LATER_START)]
    raise ValueError(name)


def evaluate_pair(selected: pd.DataFrame, control: pd.DataFrame, config: core.ScreenConfig, seed: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in (1, 2, 5):
        result[f"{horizon}d"] = {
            "selected": core.sample_metrics(selected, horizon, config, seed + horizon),
            "control": core.sample_metrics(control, horizon, config, seed + 10 + horizon),
            "paired": core.paired_difference(selected, control, horizon, 1, config, seed + 20 + horizon),
        }
    return result


def run() -> dict[str, Any]:
    if not PREREG.exists():
        raise FileNotFoundError(PREREG)
    config = b01.screen_config()
    frame = add_b03_features(b01.prepare_frame(config))
    masks = b03_masks(frame)
    cohorts = {name: frame.loc[mask].copy() for name, mask in masks.items()}
    periods = {}
    diagnostics = {}
    for i, name in enumerate(("development_2021_2023", "historical_later_2024_plus")):
        s, c = segment(cohorts["selected"], name), segment(cohorts["lower_height_control"], name)
        periods[name] = evaluate_pair(s, c, config, 5000 + i * 200)
        diagnostics[name] = {
            f"gap_{gap}_sessions": core.sample_metrics(s.loc[s["gap_sessions"].eq(gap)], 2, config, 7300 + gap)
            for gap in (2, 3)
        }
    dev, later = periods["development_2021_2023"]["2d"], periods["historical_later_2024_plus"]["2d"]
    qualification = b01.qualification_from_primary(dev, later)
    OUT.mkdir(parents=True, exist_ok=True)
    cols = ["date", "instrument", "entry_date", "entry_filled", "gap_sessions", "peak_board_height", "peak_market_max", "return_1d", "return_2d", "return_5d", "market_excess_1d", "market_excess_2d", "market_excess_5d"]
    obs = []
    for name, cohort in cohorts.items():
        if len(cohort):
            item = cohort[cols].copy(); item["cohort"] = name; obs.append(item)
    if obs:
        pd.concat(obs, ignore_index=True).to_parquet(OBSERVATIONS, index=False, compression="zstd")
    counts = {name: {"signals": int(len(c)), "active_dates": int(c["date"].nunique()), "executable": int(c["entry_filled"].fillna(False).sum())} for name, c in cohorts.items()}
    report = {"contract": CONTRACT, "preregistration_sha256": sha256_file(PREREG), "config": asdict(config), "counts": counts, "periods": periods, "diagnostics": diagnostics, "primary_qualification": qualification, "interpretation_boundary": "Frozen one-shot B03 screen; diagnostics do not modify eligibility."}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": qualification["status"], "counts": counts, "development_2d": dev, "historical_later_2d": later}, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
