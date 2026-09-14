"""M04 source-grounded leadership-dispersion representation audit."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from daily_event_role_backtest import Config as EventConfig, load_panel
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "V5_M04_LEADERSHIP_DISPERSION_SPEC.md"
M03_RESULT = ROOT / "V5_M03_RESULT.md"
OUT = ROOT / "output" / "v5_m04_leadership_dispersion"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "leadership_dispersion.parquet"
START = "2021-05-17"
END = "2026-09-03"

COLUMNS = (
    "known_industry_n",
    "positive_industry_n",
    "positive_industry_ratio",
    "first_board_industry_n",
    "seal_industry_n",
    "multi_board_industry_n",
    "seal_total",
    "seal_top1_share",
    "seal_hhi",
    "first_board_total",
    "first_board_top1_share",
    "first_board_hhi",
    "multi_board_total",
    "multi_board_top1_share",
    "multi_board_hhi",
)

CONTRACT = {
    "version": "V5_M04_LEADERSHIP_DISPERSION_V1",
    "mode": "STRUCTURAL_REPRESENTATION_ONLY",
    "uses_strategy_returns": False,
    "uses_rolling_thresholds": False,
    "parameter_search": False,
    "market_state_label_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def _distribution_stats(counts: pd.Series) -> tuple[int, float, float]:
    values = pd.to_numeric(counts, errors="coerce").fillna(0).clip(lower=0).astype(float)
    total = int(values.sum())
    if total <= 0:
        return 0, 0.0, 0.0
    shares = values / float(total)
    return total, float(shares.max()), float(np.square(shares).sum())


def build_dispersion(panel: pd.DataFrame) -> pd.DataFrame:
    required = {
        "instrument", "date", "industry_code", "ret1", "first_board", "seal_up", "board_height"
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise RuntimeError(f"M04 panel missing required fields: {missing}")

    x = panel.copy()
    x["date"] = pd.to_datetime(x["date"], errors="coerce").dt.normalize()
    if x["date"].isna().any():
        raise RuntimeError("M04 panel contains invalid dates")
    if x[["instrument", "date"]].duplicated().any():
        raise RuntimeError("M04 panel contains duplicate instrument/date rows")

    x = x.loc[x["industry_code"].fillna("UNKNOWN").astype(str).ne("UNKNOWN")].copy()
    if x.empty:
        raise RuntimeError("M04 has no point-in-time known industry rows")
    x["industry_code"] = x["industry_code"].astype(str)
    x["ret1"] = pd.to_numeric(x["ret1"], errors="coerce")
    if x["ret1"].isna().any():
        raise RuntimeError("M04 panel contains nonnumeric ret1")
    x["first_board"] = x["first_board"].fillna(False).astype(bool)
    x["seal_up"] = x["seal_up"].fillna(False).astype(bool)
    x["board_height"] = pd.to_numeric(x["board_height"], errors="coerce").fillna(0)
    x["multi_board"] = x["board_height"].ge(2)

    industry = (
        x.groupby(["date", "industry_code"], sort=True)
        .agg(
            cohort_n=("instrument", "nunique"),
            cohort_mean_return=("ret1", "mean"),
            first_board_n=("first_board", "sum"),
            seal_n=("seal_up", "sum"),
            multi_board_n=("multi_board", "sum"),
        )
        .reset_index()
    )

    rows: list[dict[str, Any]] = []
    for date, day in industry.groupby("date", sort=True):
        known_n = int(day["industry_code"].nunique())
        positive_n = int(day["cohort_mean_return"].gt(0).sum())
        seal_total, seal_top1, seal_hhi = _distribution_stats(day["seal_n"])
        first_total, first_top1, first_hhi = _distribution_stats(day["first_board_n"])
        multi_total, multi_top1, multi_hhi = _distribution_stats(day["multi_board_n"])
        rows.append({
            "date": date,
            "known_industry_n": known_n,
            "positive_industry_n": positive_n,
            "positive_industry_ratio": float(positive_n / known_n) if known_n else np.nan,
            "first_board_industry_n": int(day["first_board_n"].gt(0).sum()),
            "seal_industry_n": int(day["seal_n"].gt(0).sum()),
            "multi_board_industry_n": int(day["multi_board_n"].gt(0).sum()),
            "seal_total": seal_total,
            "seal_top1_share": seal_top1,
            "seal_hhi": seal_hhi,
            "first_board_total": first_total,
            "first_board_top1_share": first_top1,
            "first_board_hhi": first_hhi,
            "multi_board_total": multi_total,
            "multi_board_top1_share": multi_top1,
            "multi_board_hhi": multi_hhi,
        })
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def invariant_failures(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty:
        return {"empty": 1}
    industry_count_cols = [
        "positive_industry_n", "first_board_industry_n", "seal_industry_n", "multi_board_industry_n"
    ]
    ratio_cols = [
        "positive_industry_ratio", "seal_top1_share", "seal_hhi",
        "first_board_top1_share", "first_board_hhi",
        "multi_board_top1_share", "multi_board_hhi",
    ]
    failures = {
        "duplicate_dates": int(frame["date"].duplicated().sum()),
        "nonpositive_known_industry_n": int((frame["known_industry_n"] <= 0).sum()),
        "industry_count_bounds": int(sum(((frame[c] < 0) | (frame[c] > frame["known_industry_n"])).sum() for c in industry_count_cols)),
        "ratio_bounds_or_nonfinite": int(sum((~np.isfinite(frame[c].to_numpy(float)) | ~frame[c].between(0, 1)).sum() for c in ratio_cols)),
        "negative_event_totals": int(((frame[["seal_total", "first_board_total", "multi_board_total"]] < 0).sum()).sum()),
        "zero_seal_distribution": int(((frame["seal_total"] == 0) & ((frame["seal_top1_share"] != 0) | (frame["seal_hhi"] != 0))).sum()),
        "zero_first_distribution": int(((frame["first_board_total"] == 0) & ((frame["first_board_top1_share"] != 0) | (frame["first_board_hhi"] != 0))).sum()),
        "zero_multi_distribution": int(((frame["multi_board_total"] == 0) & ((frame["multi_board_top1_share"] != 0) | (frame["multi_board_hhi"] != 0))).sum()),
        "seal_hhi_gt_top1": int(((frame["seal_total"] > 0) & (frame["seal_hhi"] > frame["seal_top1_share"] + 1e-12)).sum()),
        "first_hhi_gt_top1": int(((frame["first_board_total"] > 0) & (frame["first_board_hhi"] > frame["first_board_top1_share"] + 1e-12)).sum()),
        "multi_hhi_gt_top1": int(((frame["multi_board_total"] > 0) & (frame["multi_board_hhi"] > frame["multi_board_top1_share"] + 1e-12)).sum()),
    }
    return failures


def _quantiles(frame: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in COLUMNS:
        values = pd.to_numeric(frame[c], errors="coerce").dropna()
        out[c] = {
            "n": int(len(values)),
            "q05": float(values.quantile(0.05)) if len(values) else None,
            "median": float(values.quantile(0.50)) if len(values) else None,
            "q95": float(values.quantile(0.95)) if len(values) else None,
        }
    return out


def run() -> dict[str, Any]:
    for path in (SPEC, M03_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)
    panel, metadata = load_panel(EventConfig(universe="csi800", start=START, end=END))
    frame = build_dispersion(panel)
    failures = invariant_failures(frame)
    valid = not any(failures.values())
    status = "STRUCTURALLY_VALID_FOR_DESCRIPTIVE_DISPERSION" if valid else "TECHNICALLY_INVALID"

    OUT.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OBSERVATIONS, index=False, compression="zstd")
    report = {
        "contract": CONTRACT,
        "lineage": {
            "spec_sha256": sha256_file(SPEC),
            "m03_result_sha256": sha256_file(M03_RESULT),
        },
        "status": status,
        "panel_metadata": metadata,
        "period": {
            "start": str(frame["date"].min().date()),
            "end": str(frame["date"].max().date()),
            "dates": int(len(frame)),
        },
        "invariant_failures": failures,
        "descriptive_quantiles": _quantiles(frame),
        "authorizations": {
            "descriptive_representation": valid,
            "market_state_labels": False,
            "w01_return_screen": False,
            "x02_change": False,
            "portfolio_combination": False,
            "paper_trading": False,
            "live_trading": False,
        },
        "interpretation_boundary": "M04 measures point-in-time cross-industry dispersion only. Historical quantiles may not be converted into state thresholds inside this experiment.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": status, "period": report["period"], "invariant_failures": failures}, ensure_ascii=False, indent=2))
    if not valid:
        raise SystemExit(2)
    return report


if __name__ == "__main__":
    run()
