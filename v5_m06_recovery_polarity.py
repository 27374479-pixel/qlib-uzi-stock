from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from daily_event_role_backtest import Config as EventConfig, load_panel
from v5_m01_market_tape_representation import build_market_tape
from v5_m04_leadership_dispersion import build_dispersion
from v5_m05_recovery_dynamics import build_recovery_dynamics
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "V5_M06_RECOVERY_POLARITY_SPEC.md"
M05_RESULT = ROOT / "V5_M05_RESULT.md"
OUT = ROOT / "output" / "v5_m06_recovery_polarity"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "recovery_polarity.parquet"

ORIENTATION = {
    "advance_ratio": 1,
    "decline_ratio": -1,
    "limit_down_ratio": -1,
    "seal_ratio": 1,
    "broken_ratio": -1,
    "multi_board_ratio": 1,
    "prior_seal_mean_return": 1,
    "prior_multi_board_mean_return": 1,
    "positive_industry_ratio": 1,
    "seal_industry_ratio": 1,
    "first_board_industry_ratio": 1,
    "multi_board_industry_ratio": 1,
    "seal_hhi": -1,
    "first_board_hhi": -1,
    "multi_board_hhi": -1,
}

CONTRACT = {
    "version": "V5_M06_RECOVERY_POLARITY_V1",
    "mode": "STRUCTURAL_REPRESENTATION_ONLY",
    "uses_strategy_returns": False,
    "uses_thresholds": False,
    "uses_aggregation": False,
    "parameter_search": False,
    "market_state_label_authorized": False,
    "recovery_score_authorized": False,
    "w01_return_screen_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def build_recovery_polarity(dynamics: pd.DataFrame) -> pd.DataFrame:
    x = dynamics.copy()
    x["date"] = pd.to_datetime(x["date"], errors="coerce").dt.normalize()
    if x["date"].isna().any() or x["date"].duplicated().any():
        raise RuntimeError("M06 invalid or duplicate dates")
    x = x.sort_values("date").reset_index(drop=True)
    out = pd.DataFrame({"date": x["date"]})
    for base, orientation in ORIENTATION.items():
        col = f"delta_{base}"
        if col not in x.columns:
            raise RuntimeError(f"M06 input missing {col}")
        delta = pd.to_numeric(x[col], errors="coerce")
        aligned = delta * float(orientation)
        sign = pd.Series(pd.NA, index=x.index, dtype="Int8")
        present = aligned.notna()
        sign.loc[present & aligned.gt(0)] = 1
        sign.loc[present & aligned.eq(0)] = 0
        sign.loc[present & aligned.lt(0)] = -1
        out[f"aligned_delta_{base}"] = aligned
        out[f"polarity_{base}"] = sign
    return out


def invariant_failures(dynamics: pd.DataFrame, polarity: pd.DataFrame) -> dict[str, int]:
    failures = {
        "duplicate_dates": int(polarity["date"].duplicated().sum()),
        "date_mismatch": int(list(pd.to_datetime(dynamics["date"])) != list(pd.to_datetime(polarity["date"]))),
        "aligned_delta_mismatch": 0,
        "polarity_sign_mismatch": 0,
        "missingness_not_preserved": 0,
        "first_row_delta_fabricated": 0,
    }
    if failures["date_mismatch"]:
        return failures
    for base, orientation in ORIENTATION.items():
        upstream = pd.to_numeric(dynamics[f"delta_{base}"], errors="coerce")
        aligned = pd.to_numeric(polarity[f"aligned_delta_{base}"], errors="coerce")
        sign = polarity[f"polarity_{base}"]
        present = upstream.notna()
        expected = upstream * float(orientation)
        failures["aligned_delta_mismatch"] += int((~np.isclose(aligned[present], expected[present], atol=1e-12, rtol=0)).sum())
        failures["missingness_not_preserved"] += int((upstream.isna() != aligned.isna()).sum())
        failures["missingness_not_preserved"] += int((upstream.isna() != sign.isna()).sum())
        failures["polarity_sign_mismatch"] += int((np.sign(expected[present]).astype(int).to_numpy() != sign[present].astype(int).to_numpy()).sum())
    if len(polarity):
        first = polarity.iloc[0]
        failures["first_row_delta_fabricated"] = int(sum(pd.notna(first[f"aligned_delta_{b}"]) or pd.notna(first[f"polarity_{b}"]) for b in ORIENTATION))
    return failures


def run() -> dict:
    for path in (SPEC, M05_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)
    panel, metadata = load_panel(EventConfig(universe="csi800", start="2021-05-17", end="2026-09-03"))
    dynamics = build_recovery_dynamics(build_market_tape(panel), build_dispersion(panel))
    polarity = build_recovery_polarity(dynamics)
    failures = invariant_failures(dynamics, polarity)
    valid = not any(failures.values())
    status = "STRUCTURALLY_VALID_FOR_DESCRIPTIVE_RECOVERY_POLARITY" if valid else "TECHNICALLY_INVALID"
    OUT.mkdir(parents=True, exist_ok=True)
    polarity.to_parquet(OBSERVATIONS, index=False, compression="zstd")
    report = {
        "contract": CONTRACT,
        "orientation": ORIENTATION,
        "lineage": {"spec_sha256": sha256_file(SPEC), "m05_result_sha256": sha256_file(M05_RESULT)},
        "status": status,
        "panel_metadata": metadata,
        "period": {"start": str(polarity["date"].min().date()), "end": str(polarity["date"].max().date()), "dates": int(len(polarity))},
        "invariant_failures": failures,
        "authorizations": {"descriptive_representation": valid, "market_state_labels": False, "recovery_score": False, "w01_return_screen": False, "x02_change": False, "portfolio_combination": False, "paper_trading": False, "live_trading": False},
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": status, "period": report["period"], "invariant_failures": failures}, ensure_ascii=False, indent=2))
    if not valid:
        raise SystemExit(2)
    return report


if __name__ == "__main__":
    run()
