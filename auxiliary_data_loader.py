"""Load collected auxiliary fields onto an existing point-in-time panel."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from point_in_time_data import BAOSTOCK_DAILY_DIR


INDUSTRY_DIR = Path(__file__).resolve().parent / "data_lake" / "raw" / "baostock" / "industry_snapshots"


AUXILIARY_FACTOR_COLUMNS = [
    "turnover_rate_pct",
    "trade_status",
    "is_st",
    "pe_ttm",
    "pb_mrq",
    "ps_ttm",
    "pcf_ncf_ttm",
    "float_shares_est",
    "float_market_cap_est",
]


def load_auxiliary_panel(
    target_index: pd.MultiIndex,
    data_dir: Path = BAOSTOCK_DAILY_DIR,
) -> pd.DataFrame:
    """Return exact-date auxiliary data aligned to ``(datetime, instrument)``.

    No forward/backward fill is performed.  This makes missing provider rows
    visible and prevents a later observation from leaking into an earlier date.
    """

    if not isinstance(target_index, pd.MultiIndex) or set(target_index.names) != {"datetime", "instrument"}:
        raise ValueError("target_index must have datetime and instrument levels")
    normalized = target_index.reorder_levels(["datetime", "instrument"])
    wanted_dates = pd.DatetimeIndex(normalized.get_level_values("datetime").unique())
    minimum = wanted_dates.min()
    maximum = wanted_dates.max()
    parts = []
    for instrument in sorted(normalized.get_level_values("instrument").unique()):
        path = data_dir / f"{instrument}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(
            path,
            columns=["instrument", "date", *AUXILIARY_FACTOR_COLUMNS],
            filters=[("date", ">=", minimum), ("date", "<=", maximum)],
        )
        frame = frame.loc[frame["date"].isin(wanted_dates)].rename(columns={"date": "datetime"})
        parts.append(frame)
    if not parts:
        return pd.DataFrame(index=normalized, columns=AUXILIARY_FACTOR_COLUMNS, dtype=float)
    result = pd.concat(parts, ignore_index=True).set_index(["datetime", "instrument"]).sort_index()
    result = result[~result.index.duplicated(keep="last")]
    return result.reindex(normalized)[AUXILIARY_FACTOR_COLUMNS]


def coverage_report(frame: pd.DataFrame) -> dict:
    return {
        "rows": len(frame),
        "instruments": int(frame.index.get_level_values("instrument").nunique()) if len(frame) else 0,
        "dates": int(frame.index.get_level_values("datetime").nunique()) if len(frame) else 0,
        "column_coverage": {column: float(frame[column].notna().mean()) for column in frame.columns},
        "fully_missing_rows": int(frame.isna().all(axis=1).sum()),
    }


def load_industry_panel(target_index: pd.MultiIndex, data_dir: Path = INDUSTRY_DIR) -> pd.DataFrame:
    """Load the industry snapshot published for each exact signal date."""

    if not isinstance(target_index, pd.MultiIndex) or set(target_index.names) != {"datetime", "instrument"}:
        raise ValueError("target_index must have datetime and instrument levels")
    normalized = target_index.reorder_levels(["datetime", "instrument"])
    parts = []
    for date in pd.DatetimeIndex(normalized.get_level_values("datetime").unique()):
        path = data_dir / f"{date:%Y%m%d}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(
            path,
            columns=[
                "snapshot_date",
                "instrument",
                "industry_code",
                "industry",
                "classification_standard",
                "provider_update_date",
            ],
        ).rename(columns={"snapshot_date": "datetime"})
        parts.append(frame)
    columns = ["industry_code", "industry", "classification_standard", "provider_update_date"]
    if not parts:
        return pd.DataFrame(index=normalized, columns=columns)
    result = pd.concat(parts, ignore_index=True).set_index(["datetime", "instrument"])
    result = result[~result.index.duplicated(keep="last")]
    return result.reindex(normalized)[columns]
