"""M01 structural audit for a source-grounded market-tape representation.

M01 intentionally does not classify regimes and does not evaluate forward
returns.  It records completed-close market observables named by the supplied
48-trader books and verifies accounting / point-in-time invariants only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from daily_event_role_backtest import Config as EventConfig, load_panel
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "V5_M01_MARKET_TAPE_REPRESENTATION_SPEC.md"
OUT = ROOT / "output" / "v5_m01_market_tape_representation"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "market_tape.parquet"

START = "2021-05-17"
END = "2026-09-03"

TAPE_COLUMNS = (
    "universe_n",
    "advance_count",
    "decline_count",
    "flat_count",
    "breadth",
    "touch_count",
    "seal_count",
    "broken_count",
    "broken_ratio",
    "limit_down_count",
    "max_board_height",
    "multi_board_count",
    "prior_seal_sample_n",
    "prior_seal_mean_return",
    "prior_multi_board_sample_n",
    "prior_multi_board_mean_return",
)

CONTRACT = {
    "version": "V5_M01_MARKET_TAPE_REPRESENTATION_V1",
    "mode": "STRUCTURAL_REPRESENTATION_ONLY",
    "source": [
        "user-supplied lower 48-trader volume, PDF pp.71-73/227",
        "user-supplied lower 48-trader volume, PDF pp.100-103/227",
        "user-supplied upper 48-trader volume, total-leader trait list",
    ],
    "observables": list(TAPE_COLUMNS),
    "uses_forward_returns": False,
    "uses_rolling_thresholds": False,
    "parameter_search": False,
    "regime_labels_authorized": False,
    "alpha_evaluation_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def _require_columns(frame: pd.DataFrame) -> None:
    required = {
        "instrument",
        "date",
        "ret1",
        "touch_up",
        "seal_up",
        "broken_up",
        "limit_down_close",
        "board_height",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"M01 panel missing required fields: {missing}")


def build_market_tape(frame: pd.DataFrame) -> pd.DataFrame:
    """Build one completed-close market-tape row per date.

    Only same-row completed-close values and lagged identity flags are used.
    No future shift, forward return, rolling threshold or regime label is
    constructed here.
    """

    _require_columns(frame)
    x = frame.copy()
    x["date"] = pd.to_datetime(x["date"], errors="coerce").dt.normalize()
    if x["date"].isna().any():
        raise RuntimeError("M01 panel contains invalid dates")
    if x[["instrument", "date"]].duplicated().any():
        n = int(x[["instrument", "date"]].duplicated(keep=False).sum())
        raise RuntimeError(f"M01 panel contains duplicate instrument/date rows: {n}")

    x = x.sort_values(["instrument", "date"]).reset_index(drop=True)
    x["ret_num"] = pd.to_numeric(x["ret1"], errors="coerce")
    if x["ret_num"].isna().any():
        raise RuntimeError("M01 panel contains non-numeric ret1 values")

    for column in ("touch_up", "seal_up", "broken_up", "limit_down_close"):
        x[column] = x[column].fillna(False).astype(bool)
    x["board_num"] = pd.to_numeric(x["board_height"], errors="coerce").fillna(0)

    g = x.groupby("instrument", sort=False)
    x["prior_seal"] = g["seal_up"].shift(1).fillna(False).astype(bool)
    x["prior_multi_board"] = g["board_num"].shift(1).fillna(0).ge(2)

    x["advance"] = x["ret_num"].gt(0)
    x["decline"] = x["ret_num"].lt(0)
    x["flat"] = ~(x["advance"] | x["decline"])
    x["multi_board"] = x["board_num"].ge(2)

    rows: list[dict[str, Any]] = []
    for date, day in x.groupby("date", sort=True):
        universe_n = int(len(day))
        touch_count = int(day["touch_up"].sum())
        seal_count = int(day["seal_up"].sum())
        broken_count = int(day["broken_up"].sum())
        prior_seal = day.loc[day["prior_seal"], "ret_num"]
        prior_multi = day.loc[day["prior_multi_board"], "ret_num"]
        rows.append(
            {
                "date": date,
                "universe_n": universe_n,
                "advance_count": int(day["advance"].sum()),
                "decline_count": int(day["decline"].sum()),
                "flat_count": int(day["flat"].sum()),
                "breadth": float((day["advance"].sum() - day["decline"].sum()) / universe_n)
                if universe_n
                else np.nan,
                "touch_count": touch_count,
                "seal_count": seal_count,
                "broken_count": broken_count,
                "broken_ratio": float(broken_count / max(touch_count, 1)),
                "limit_down_count": int(day["limit_down_close"].sum()),
                "max_board_height": int(day["board_num"].max()) if universe_n else 0,
                "multi_board_count": int(day["multi_board"].sum()),
                "prior_seal_sample_n": int(len(prior_seal)),
                "prior_seal_mean_return": float(prior_seal.mean()) if len(prior_seal) else np.nan,
                "prior_multi_board_sample_n": int(len(prior_multi)),
                "prior_multi_board_mean_return": float(prior_multi.mean()) if len(prior_multi) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def invariant_failures(tape: pd.DataFrame) -> dict[str, int]:
    if tape.empty:
        return {"empty_tape": 1}

    count_columns = [
        "universe_n",
        "advance_count",
        "decline_count",
        "flat_count",
        "touch_count",
        "seal_count",
        "broken_count",
        "limit_down_count",
        "multi_board_count",
        "prior_seal_sample_n",
        "prior_multi_board_sample_n",
    ]
    missing = [column for column in TAPE_COLUMNS if column not in tape.columns]
    failures: dict[str, int] = {
        "duplicate_dates": int(tape["date"].duplicated().sum()),
        "missing_source_dimensions": len(missing),
        "advance_decline_flat_accounting": int(
            (
                tape["advance_count"]
                + tape["decline_count"]
                + tape["flat_count"]
                != tape["universe_n"]
            ).sum()
        ),
        "seal_exceeds_touch": int((tape["seal_count"] > tape["touch_count"]).sum()),
        "touch_exceeds_universe": int((tape["touch_count"] > tape["universe_n"]).sum()),
        "broken_accounting": int(
            (tape["broken_count"] != tape["touch_count"] - tape["seal_count"]).sum()
        ),
        "multi_board_exceeds_seal": int((tape["multi_board_count"] > tape["seal_count"]).sum()),
        "negative_or_oversized_counts": int(
            sum(((tape[column] < 0) | (tape[column] > tape["universe_n"])).sum() for column in count_columns)
        ),
        "breadth_out_of_bounds": int((~tape["breadth"].between(-1.0, 1.0)).sum()),
        "broken_ratio_out_of_bounds": int((~tape["broken_ratio"].between(0.0, 1.0)).sum()),
        "nonfinite_breadth": int((~np.isfinite(tape["breadth"].to_numpy(float))).sum()),
        "nonfinite_broken_ratio": int((~np.isfinite(tape["broken_ratio"].to_numpy(float))).sum()),
        "prior_seal_mean_invalid": int(
            ((tape["prior_seal_sample_n"] > 0) & ~np.isfinite(tape["prior_seal_mean_return"].to_numpy(float))).sum()
        ),
        "prior_multi_mean_invalid": int(
            ((tape["prior_multi_board_sample_n"] > 0) & ~np.isfinite(tape["prior_multi_board_mean_return"].to_numpy(float))).sum()
        ),
    }
    return failures


def _quantiles(tape: pd.DataFrame) -> dict[str, Any]:
    columns = [
        "breadth",
        "touch_count",
        "seal_count",
        "broken_ratio",
        "limit_down_count",
        "max_board_height",
        "multi_board_count",
        "prior_seal_mean_return",
        "prior_multi_board_mean_return",
    ]
    out: dict[str, Any] = {}
    for column in columns:
        values = pd.to_numeric(tape[column], errors="coerce").dropna()
        out[column] = {
            "n": int(len(values)),
            "q05": float(values.quantile(0.05)) if len(values) else None,
            "q25": float(values.quantile(0.25)) if len(values) else None,
            "median": float(values.quantile(0.50)) if len(values) else None,
            "q75": float(values.quantile(0.75)) if len(values) else None,
            "q95": float(values.quantile(0.95)) if len(values) else None,
        }
    return out


def _year_summary(tape: pd.DataFrame) -> list[dict[str, Any]]:
    x = tape.copy()
    x["year"] = pd.to_datetime(x["date"]).dt.year
    rows: list[dict[str, Any]] = []
    for year, group in x.groupby("year", sort=True):
        rows.append(
            {
                "year": int(year),
                "dates": int(len(group)),
                "breadth_mean": float(group["breadth"].mean()),
                "seal_count_median": float(group["seal_count"].median()),
                "broken_ratio_median": float(group["broken_ratio"].median()),
                "limit_down_count_median": float(group["limit_down_count"].median()),
                "max_board_height_median": float(group["max_board_height"].median()),
            }
        )
    return rows


def run() -> dict[str, Any]:
    if not SPEC.exists():
        raise FileNotFoundError(SPEC)

    panel, metadata = load_panel(EventConfig(universe="csi800", start=START, end=END))
    tape = build_market_tape(panel)
    failures = invariant_failures(tape)
    structural_valid = not any(failures.values())
    status = (
        "STRUCTURALLY_VALID_FOR_DESCRIPTIVE_MARKET_TAPE"
        if structural_valid
        else "TECHNICALLY_INVALID"
    )

    OUT.mkdir(parents=True, exist_ok=True)
    tape.to_parquet(OBSERVATIONS, index=False, compression="zstd")

    numeric = [column for column in TAPE_COLUMNS if column in tape.columns]
    corr = tape[numeric].corr(numeric_only=True).round(6).replace({np.nan: None})
    report = {
        "contract": CONTRACT,
        "spec_sha256": sha256_file(SPEC),
        "status": status,
        "panel_metadata": metadata,
        "period": {
            "start": str(tape["date"].min().date()) if len(tape) else None,
            "end": str(tape["date"].max().date()) if len(tape) else None,
            "dates": int(len(tape)),
        },
        "invariant_failures": failures,
        "coverage": {
            "prior_seal_mean_available_dates": int(tape["prior_seal_mean_return"].notna().sum()),
            "prior_multi_board_mean_available_dates": int(tape["prior_multi_board_mean_return"].notna().sum()),
            "source_dimensions": list(TAPE_COLUMNS),
        },
        "descriptive_quantiles": _quantiles(tape),
        "year_summary": _year_summary(tape),
        "correlation_matrix": corr.to_dict(),
        "authorizations": {
            "descriptive_representation": bool(structural_valid),
            "regime_labels": False,
            "alpha_evaluation": False,
            "w01_return_screen": False,
            "x02_change": False,
            "portfolio_combination": False,
            "paper_trading": False,
            "live_trading": False,
        },
        "interpretation_boundary": (
            "M01 validates only that the source-grounded market tape can be represented causally and coherently. "
            "No quantile, correlation or year statistic may be converted into a regime threshold inside M01."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "status": status,
        "period": report["period"],
        "invariant_failures": failures,
        "coverage": report["coverage"],
    }, ensure_ascii=False, indent=2))
    if not structural_valid:
        raise SystemExit(2)
    return report


if __name__ == "__main__":
    run()
