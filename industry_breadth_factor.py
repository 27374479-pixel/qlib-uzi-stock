"""Industry breadth and new-high diffusion factors.

Motivated by the ChatGPT round-10 research finding that "行业广度 + 阶段新高"
improved Sharpe from 0.799 to 0.836 and reduced max drawdown from -27.86% to
-22.80%.  This module implements the factor construction in a way that is
compatible with the existing enriched_factor_backtest panel.

Two factors are computed per instrument on each signal date:

  industry_new_high_breadth
      The fraction of stocks in the same CSRC industry that are within 10% of
      their 60-day rolling high.  A high value means the industry is broadly
      strong, not just a single leader.

  cross_industry_diffusion
      The fraction of all CSRC industries where >50% of members are above
      their 20-day moving average.  This is a market-wide regime indicator
      that captures breadth across sectors.

Both factors use only data available at signal-date close (no lookahead).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from auxiliary_data_loader import INDUSTRY_DIR
from factor_transfer_backtest import RawQlibStore, calendar, point_in_time_members


BREADTH_FEATURES = (
    "industry_new_high_breadth",
    "cross_industry_diffusion",
)

NEW_HIGH_THRESHOLD = 0.10  # within 10% of 60-day high
MA_PERIOD = 20
HIGH_PERIOD = 60
DIFFUSION_MAJORITY = 0.50


def _load_industry_for_date(date: pd.Timestamp, data_dir: Path = INDUSTRY_DIR) -> pd.DataFrame:
    path = data_dir / f"{date:%Y%m%d}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["instrument", "industry_code"])
    frame = pd.read_parquet(path, columns=["instrument", "industry_code"])
    return frame.dropna(subset=["instrument", "industry_code"]).drop_duplicates("instrument")


def compute_breadth_for_date(
    date: pd.Timestamp,
    members: list[str],
    store: RawQlibStore,
    cal: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Compute breadth factors for all members on a single signal date."""

    t = int(cal.searchsorted(date))
    industry_frame = _load_industry_for_date(date)
    if industry_frame.empty:
        return pd.DataFrame(
            {"industry_new_high_breadth": np.nan, "cross_industry_diffusion": np.nan},
            index=pd.Index(members, name="instrument"),
        )

    industry_map = dict(zip(industry_frame["instrument"], industry_frame["industry_code"]))

    near_high = {}
    above_ma = {}

    for instrument in members:
        close = store.window(instrument, "close", t - HIGH_PERIOD, t)
        if not np.isfinite(close).any():
            continue
        current = float(close[-1])
        high_60 = float(np.nanmax(close))
        if high_60 > 0 and np.isfinite(current):
            near_high[instrument] = current >= high_60 * (1 - NEW_HIGH_THRESHOLD)

        ma_slice = close[-MA_PERIOD:]
        valid_ma = ma_slice[np.isfinite(ma_slice)]
        if len(valid_ma) >= MA_PERIOD // 2:
            ma_value = float(valid_ma.mean())
            above_ma[instrument] = current > ma_value

    ind_groups: dict[str, list[str]] = {}
    for instrument in members:
        code = industry_map.get(instrument)
        if code:
            ind_groups.setdefault(code, []).append(instrument)

    ind_breadth: dict[str, float] = {}
    for code, group_members in ind_groups.items():
        hits = sum(1 for m in group_members if near_high.get(m, False))
        ind_breadth[code] = hits / len(group_members) if group_members else 0.0

    total_industries = len(ind_groups)
    if total_industries > 0:
        diffusing = sum(
            1
            for code, group_members in ind_groups.items()
            if (
                sum(1 for m in group_members if above_ma.get(m, False)) / len(group_members)
                > DIFFUSION_MAJORITY
            )
        )
        diffusion_value = diffusing / total_industries
    else:
        diffusion_value = np.nan

    rows = {}
    for instrument in members:
        code = industry_map.get(instrument)
        rows[instrument] = {
            "industry_new_high_breadth": ind_breadth.get(code, np.nan) if code else np.nan,
            "cross_industry_diffusion": diffusion_value,
        }

    return pd.DataFrame.from_dict(rows, orient="index")


def compute_breadth_panel(
    dates: list[pd.Timestamp],
    market: str = "csi800",
    cache_path: Path | None = None,
) -> pd.DataFrame:
    """Build a full (datetime, instrument) panel of breadth factors."""

    if cache_path is not None and cache_path.exists():
        print(f"Loading cached breadth panel: {cache_path}", flush=True)
        return pd.read_pickle(cache_path)

    cal = calendar()
    memberships = point_in_time_members(market, dates)
    store = RawQlibStore()
    parts = []

    for number, date in enumerate(dates, 1):
        members = memberships[date]
        frame = compute_breadth_for_date(date, members, store, cal)
        frame["datetime"] = date
        frame.index.name = "instrument"
        frame = frame.reset_index().set_index(["datetime", "instrument"])
        parts.append(frame)
        if number == 1 or number % 12 == 0:
            print(f"  breadth {number}/{len(dates)}: {date.date()} ({len(members)} members)", flush=True)

    result = pd.concat(parts).sort_index()
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(".tmp")
        result.to_pickle(temporary)
        temporary.replace(cache_path)
        print(f"Cached breadth panel: {cache_path}", flush=True)

    return result
