"""M05 causal/descriptive recovery-dynamics representation.

M05 transforms only already source-grounded M01/M04 completed-close levels.
It does not classify market states and never inspects strategy returns.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from daily_event_role_backtest import Config as EventConfig, load_panel
from v5_m01_market_tape_representation import build_market_tape
from v5_m04_leadership_dispersion import build_dispersion
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "V5_M05_RECOVERY_DYNAMICS_SPEC.md"
M01_RESULT = ROOT / "V5_M01_RESULT.md"
M04_RESULT = ROOT / "V5_M04_RESULT.md"
OUT = ROOT / "output" / "v5_m05_recovery_dynamics"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "recovery_dynamics.parquet"
START = "2021-05-17"
END = "2026-09-03"

LEVEL_COLUMNS = (
    "advance_ratio",
    "decline_ratio",
    "limit_down_ratio",
    "seal_ratio",
    "broken_ratio",
    "multi_board_ratio",
    "prior_seal_mean_return",
    "prior_multi_board_mean_return",
    "positive_industry_ratio",
    "seal_industry_ratio",
    "first_board_industry_ratio",
    "multi_board_industry_ratio",
    "seal_hhi",
    "first_board_hhi",
    "multi_board_hhi",
)

BOUNDED_LEVELS = (
    "advance_ratio",
    "decline_ratio",
    "limit_down_ratio",
    "seal_ratio",
    "broken_ratio",
    "multi_board_ratio",
    "positive_industry_ratio",
    "seal_industry_ratio",
    "first_board_industry_ratio",
    "multi_board_industry_ratio",
    "seal_hhi",
    "first_board_hhi",
    "multi_board_hhi",
)

RETURN_LEVELS = ("prior_seal_mean_return", "prior_multi_board_mean_return")
DELTA_COLUMNS = tuple(f"delta_{column}" for column in LEVEL_COLUMNS)

CONTRACT = {
    "version": "V5_M05_RECOVERY_DYNAMICS_V1",
    "mode": "STRUCTURAL_REPRESENTATION_ONLY",
    "difference_horizon_completed_sessions": 1,
    "missing_prior_winner_returns_filled_with_zero": False,
    "uses_strategy_returns": False,
    "uses_fitted_thresholds": False,
    "parameter_search": False,
    "market_state_label_authorized": False,
    "recovery_score_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def build_recovery_dynamics(tape: pd.DataFrame, dispersion: pd.DataFrame) -> pd.DataFrame:
    """Join frozen M01/M04 levels and add one-session first differences."""
    left = tape.copy()
    right = dispersion.copy()
    left["date"] = pd.to_datetime(left["date"], errors="coerce").dt.normalize()
    right["date"] = pd.to_datetime(right["date"], errors="coerce").dt.normalize()
    if left["date"].isna().any() or right["date"].isna().any():
        raise RuntimeError("M05 inputs contain invalid dates")
    if left["date"].duplicated().any() or right["date"].duplicated().any():
        raise RuntimeError("M05 inputs must have one row per date")
    if set(left["date"]) != set(right["date"]):
        missing_left = len(set(right["date"]) - set(left["date"]))
        missing_right = len(set(left["date"]) - set(right["date"]))
        raise RuntimeError(
            f"M05 date lineage mismatch: missing_from_m01={missing_left}, missing_from_m04={missing_right}"
        )

    x = left.merge(
        right[
            [
                "date",
                "known_industry_n",
                "positive_industry_ratio",
                "seal_industry_n",
                "first_board_industry_n",
                "multi_board_industry_n",
                "seal_hhi",
                "first_board_hhi",
                "multi_board_hhi",
            ]
        ],
        on="date",
        how="inner",
        validate="one_to_one",
    ).sort_values("date").reset_index(drop=True)

    if (x["universe_n"] <= 0).any() or (x["known_industry_n"] <= 0).any():
        raise RuntimeError("M05 input denominator is nonpositive")

    x["advance_ratio"] = x["advance_count"] / x["universe_n"]
    x["decline_ratio"] = x["decline_count"] / x["universe_n"]
    x["limit_down_ratio"] = x["limit_down_count"] / x["universe_n"]
    x["seal_ratio"] = x["seal_count"] / x["universe_n"]
    x["multi_board_ratio"] = x["multi_board_count"] / x["universe_n"]
    x["seal_industry_ratio"] = x["seal_industry_n"] / x["known_industry_n"]
    x["first_board_industry_ratio"] = x["first_board_industry_n"] / x["known_industry_n"]
    x["multi_board_industry_ratio"] = x["multi_board_industry_n"] / x["known_industry_n"]

    for column in LEVEL_COLUMNS:
        x[column] = pd.to_numeric(x[column], errors="coerce")
        x[f"delta_{column}"] = x[column].diff(1)

    return x[["date", *LEVEL_COLUMNS, *DELTA_COLUMNS]].copy()


def invariant_failures(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty:
        return {"empty": 1}

    failures: dict[str, int] = {
        "duplicate_dates": int(frame["date"].duplicated().sum()),
        "bounded_level_out_of_range_or_nonfinite": 0,
        "bounded_delta_out_of_range_or_nonfinite": 0,
        "return_level_nonfinite_when_present": 0,
        "return_delta_nonfinite_when_present": 0,
        "first_row_delta_fabricated": 0,
    }

    for column in BOUNDED_LEVELS:
        values = pd.to_numeric(frame[column], errors="coerce")
        failures["bounded_level_out_of_range_or_nonfinite"] += int(
            ((~np.isfinite(values.to_numpy(float))) | (~values.between(0.0, 1.0))).sum()
        )
        delta = pd.to_numeric(frame[f"delta_{column}"], errors="coerce")
        present = delta.notna()
        failures["bounded_delta_out_of_range_or_nonfinite"] += int(
            ((present & ~np.isfinite(delta.to_numpy(float))) | (present & ~delta.between(-1.0, 1.0))).sum()
        )

    for column in RETURN_LEVELS:
        values = pd.to_numeric(frame[column], errors="coerce")
        present = values.notna()
        failures["return_level_nonfinite_when_present"] += int(
            (present & ~np.isfinite(values.to_numpy(float))).sum()
        )
        delta = pd.to_numeric(frame[f"delta_{column}"], errors="coerce")
        delta_present = delta.notna()
        failures["return_delta_nonfinite_when_present"] += int(
            (delta_present & ~np.isfinite(delta.to_numpy(float))).sum()
        )

    first = frame.iloc[0]
    failures["first_row_delta_fabricated"] = int(
        sum(pd.notna(first[column]) for column in DELTA_COLUMNS)
    )
    return failures


def _descriptive_quantiles(frame: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in DELTA_COLUMNS:
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        out[column] = {
            "n": int(len(values)),
            "q05": float(values.quantile(0.05)) if len(values) else None,
            "median": float(values.quantile(0.50)) if len(values) else None,
            "q95": float(values.quantile(0.95)) if len(values) else None,
        }
    return out


def run() -> dict[str, Any]:
    for path in (SPEC, M01_RESULT, M04_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)

    panel, metadata = load_panel(EventConfig(universe="csi800", start=START, end=END))
    tape = build_market_tape(panel)
    dispersion = build_dispersion(panel)
    frame = build_recovery_dynamics(tape, dispersion)
    failures = invariant_failures(frame)
    valid = not any(failures.values())
    status = (
        "STRUCTURALLY_VALID_FOR_DESCRIPTIVE_RECOVERY_DYNAMICS"
        if valid
        else "TECHNICALLY_INVALID"
    )

    OUT.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OBSERVATIONS, index=False, compression="zstd")
    report = {
        "contract": CONTRACT,
        "lineage": {
            "spec_sha256": sha256_file(SPEC),
            "m01_result_sha256": sha256_file(M01_RESULT),
            "m04_result_sha256": sha256_file(M04_RESULT),
        },
        "status": status,
        "panel_metadata": metadata,
        "period": {
            "start": str(frame["date"].min().date()),
            "end": str(frame["date"].max().date()),
            "dates": int(len(frame)),
        },
        "invariant_failures": failures,
        "coverage": {
            "prior_seal_level_dates": int(frame["prior_seal_mean_return"].notna().sum()),
            "prior_seal_delta_dates": int(frame["delta_prior_seal_mean_return"].notna().sum()),
            "prior_multi_level_dates": int(frame["prior_multi_board_mean_return"].notna().sum()),
            "prior_multi_delta_dates": int(frame["delta_prior_multi_board_mean_return"].notna().sum()),
        },
        "descriptive_delta_quantiles": _descriptive_quantiles(frame),
        "authorizations": {
            "descriptive_representation": valid,
            "market_state_labels": False,
            "recovery_score": False,
            "w01_return_screen": False,
            "x02_change": False,
            "portfolio_combination": False,
            "paper_trading": False,
            "live_trading": False,
        },
        "interpretation_boundary": (
            "M05 represents one-session changes in frozen source-grounded tape dimensions. "
            "No sign combination, quantile or historical distribution may be promoted to a recovery classifier inside M05."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": status,
                "period": report["period"],
                "invariant_failures": failures,
                "coverage": report["coverage"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not valid:
        raise SystemExit(2)
    return report


if __name__ == "__main__":
    run()
