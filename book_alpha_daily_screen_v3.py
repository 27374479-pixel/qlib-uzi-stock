"""Canonical v3 book-alpha daily screen with true observed listing age.

``daily_event_role_backtest.history_n`` is counted *after* point-in-time index
membership filtering, so it measures index-tenure history rather than listing
age.  v3 derives observed trading age from each instrument's complete BaoStock
daily file before applying the >=120-session eligibility rule.

For securities already listed before the data-lake start (2014-01-01), the
observed age is a conservative lower bound; by the 2015 signal start they are
already above 120 sessions.  For later IPOs it tracks the provider's historical
daily rows directly.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import book_alpha_daily_screen_v2 as v2
from daily_event_role_backtest import DAILY_DIR

ScreenConfig = v2.ScreenConfig


def _observed_age(path: Path, dates: pd.Series) -> np.ndarray:
    raw = pd.read_parquet(path, columns=["date"])
    all_dates = pd.DatetimeIndex(
        pd.to_datetime(raw["date"], errors="coerce").dropna().dt.normalize().drop_duplicates().sort_values()
    )
    target = pd.DatetimeIndex(pd.to_datetime(dates, errors="coerce").dt.normalize())
    if all_dates.empty:
        return np.zeros(len(target), dtype=np.int64)
    # searchsorted-right counts all observed provider rows up to the signal date.
    # Use one explicit dtype end-to-end. Pandas 3.x rejects implicit assignment
    # between int64 ndarray values and an int32 Series (LossySetitemError).
    return all_dates.searchsorted(target, side="right").astype(np.int64, copy=False)


def enforce_true_listing_policy(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = frame.copy()
    # int64 matches DatetimeIndex.searchsorted's natural integer dtype and avoids
    # Pandas 3.x strict setitem coercion failures. Values are only session counts.
    ages = pd.Series(0, index=frame.index, dtype="int64")
    missing_files: list[str] = []
    for instrument, index in frame.groupby("instrument", sort=False).groups.items():
        path = DAILY_DIR / f"{instrument}.parquet"
        if not path.exists():
            missing_files.append(str(instrument))
            continue
        group_index = pd.Index(index)
        ages.loc[group_index] = _observed_age(path, frame.loc[group_index, "date"])
    frame["observed_listing_sessions"] = ages
    board_mask = frame["instrument"].astype(str).map(v2._allowed_instrument)
    mature_mask = frame["observed_listing_sessions"].ge(120)
    result = frame.loc[board_mask & mature_mask].copy()
    meta = {
        "policy": "mainboard_chinext_no_star_historical_st_removed_observed_listing_sessions_ge120_v2",
        "listing_age_source": "complete BaoStock daily file rows before point-in-time index membership filtering",
        "rows_before_policy": int(len(frame)),
        "rows_after_policy": int(len(result)),
        "instruments_after_policy": int(result["instrument"].nunique()),
        "removed_rows": int(len(frame) - len(result)),
        "missing_daily_files_for_age": missing_files,
    }
    if missing_files:
        raise FileNotFoundError(f"cannot determine listing age for {len(missing_files)} instruments: {missing_files[:10]}")
    return result, meta


def run(config: ScreenConfig):
    # v2.run resolves this module-level function dynamically, so patching it is
    # sufficient while keeping all hypothesis/metric code single-sourced.
    original = v2.enforce_universe_policy
    v2.enforce_universe_policy = enforce_true_listing_policy
    try:
        return v2.run(config)
    finally:
        v2.enforce_universe_policy = original


def parse_args() -> ScreenConfig:
    parser = argparse.ArgumentParser(description="Canonical v3 book alpha screen with true listing age")
    parser.add_argument("--universe", default=ScreenConfig.universe)
    parser.add_argument("--start", default=ScreenConfig.start)
    parser.add_argument("--end", default=ScreenConfig.end)
    parser.add_argument("--oos-start", default=ScreenConfig.oos_start)
    parser.add_argument("--round-trip-cost", type=float, default=ScreenConfig.round_trip_cost)
    parser.add_argument("--bootstrap-samples", type=int, default=ScreenConfig.bootstrap_samples)
    parser.add_argument("--seed", type=int, default=ScreenConfig.seed)
    parser.add_argument("--min-oos-observations", type=int, default=ScreenConfig.min_oos_observations)
    parser.add_argument("--min-oos-days", type=int, default=ScreenConfig.min_oos_days)
    parser.add_argument("--output", default="output/book_alpha_daily_screen_v3.json")
    parser.add_argument("--observations-output", default="output/book_alpha_daily_screen_observations_v3.parquet")
    return ScreenConfig(**vars(parser.parse_args()))


if __name__ == "__main__":
    run(parse_args())
