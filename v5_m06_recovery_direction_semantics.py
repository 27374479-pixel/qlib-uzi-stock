"""Directional semantics over the frozen M05 market-context deltas."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

from daily_event_role_backtest import Config as EventConfig, load_panel
from v5_m01_market_tape_representation import build_market_tape
from v5_m04_leadership_dispersion import build_dispersion
from v5_m05_recovery_dynamics import LEVEL_COLUMNS, build_recovery_dynamics
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "V5_M06_RECOVERY_DIRECTION_SEMANTICS_SPEC.md"
M05_RESULT = ROOT / "V5_M05_RESULT.md"
OUT = ROOT / "output" / "v5_m06_recovery_direction_semantics"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "recovery_direction_semantics.parquet"
START, END = "2021-05-17", "2026-09-03"

# +1: higher delta is improving; -1: lower delta is improving.
POLARITY = {
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
DIRECTION_COLUMNS = tuple(f"direction_{c}" for c in LEVEL_COLUMNS)
COUNT_COLUMNS = (
    "improving_dimension_n",
    "deteriorating_dimension_n",
    "unchanged_dimension_n",
    "available_dimension_n",
    "unavailable_dimension_n",
)
CONTRACT = {
    "version": "V5_M06_RECOVERY_DIRECTION_SEMANTICS_V1",
    "mode": "STRUCTURAL_REPRESENTATION_ONLY",
    "zero_is_neutral": True,
    "missing_delta_imputation": False,
    "parameter_search": False,
    "aggregate_recovery_score_authorized": False,
    "market_state_label_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def validate_polarity() -> None:
    if set(POLARITY) != set(LEVEL_COLUMNS):
        raise RuntimeError("M06 polarity does not exactly cover frozen M05 levels")
    if any(v not in (-1, 1) for v in POLARITY.values()):
        raise RuntimeError("M06 polarity values must be +/-1")


def build_direction_semantics(dynamics: pd.DataFrame) -> pd.DataFrame:
    validate_polarity()
    required = {"date", *(f"delta_{c}" for c in LEVEL_COLUMNS)}
    missing = sorted(required - set(dynamics.columns))
    if missing:
        raise RuntimeError(f"M06 missing fields: {missing}")
    x = dynamics.copy()
    x["date"] = pd.to_datetime(x["date"], errors="coerce").dt.normalize()
    if x["date"].isna().any() or x["date"].duplicated().any():
        raise RuntimeError("M06 requires unique valid dates")
    x = x.sort_values("date").reset_index(drop=True)

    for c in LEVEL_COLUMNS:
        delta = pd.to_numeric(x[f"delta_{c}"], errors="coerce")
        signed = delta * POLARITY[c]
        out = pd.Series(pd.NA, index=x.index, dtype="Int8")
        present = delta.notna()
        out.loc[present & signed.gt(0)] = 1
        out.loc[present & signed.lt(0)] = -1
        out.loc[present & signed.eq(0)] = 0
        x[f"direction_{c}"] = out

    d = x[list(DIRECTION_COLUMNS)]
    x["improving_dimension_n"] = d.eq(1).sum(axis=1).astype(int)
    x["deteriorating_dimension_n"] = d.eq(-1).sum(axis=1).astype(int)
    x["unchanged_dimension_n"] = d.eq(0).sum(axis=1).astype(int)
    x["available_dimension_n"] = d.notna().sum(axis=1).astype(int)
    x["unavailable_dimension_n"] = len(DIRECTION_COLUMNS) - x["available_dimension_n"]
    return x[["date", *DIRECTION_COLUMNS, *COUNT_COLUMNS]].copy()


def invariant_failures(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty:
        return {"empty": 1}
    invalid = 0
    for c in DIRECTION_COLUMNS:
        values = frame[c].dropna().astype(int)
        invalid += int((~values.isin([-1, 0, 1])).sum())
    available_from_parts = (
        frame["improving_dimension_n"]
        + frame["deteriorating_dimension_n"]
        + frame["unchanged_dimension_n"]
    )
    return {
        "duplicate_dates": int(frame["date"].duplicated().sum()),
        "invalid_direction_values": invalid,
        "direction_count_accounting": int((available_from_parts != frame["available_dimension_n"]).sum()),
        "availability_count_accounting": int(((frame["available_dimension_n"] + frame["unavailable_dimension_n"]) != len(DIRECTION_COLUMNS)).sum()),
        "first_row_direction_fabricated": int(sum(pd.notna(frame.iloc[0][c]) for c in DIRECTION_COLUMNS)),
    }


def run() -> dict:
    for p in (SPEC, M05_RESULT):
        if not p.exists():
            raise FileNotFoundError(p)
    panel, metadata = load_panel(EventConfig(universe="csi800", start=START, end=END))
    dynamics = build_recovery_dynamics(build_market_tape(panel), build_dispersion(panel))
    frame = build_direction_semantics(dynamics)
    failures = invariant_failures(frame)
    valid = not any(failures.values())
    status = "STRUCTURALLY_VALID_FOR_DESCRIPTIVE_DIRECTION_SEMANTICS" if valid else "TECHNICALLY_INVALID"
    OUT.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OBSERVATIONS, index=False, compression="zstd")
    report = {
        "contract": CONTRACT,
        "lineage": {"spec_sha256": sha256_file(SPEC), "m05_result_sha256": sha256_file(M05_RESULT)},
        "status": status,
        "panel_metadata": metadata,
        "period": {"start": str(frame["date"].min().date()), "end": str(frame["date"].max().date()), "dates": int(len(frame))},
        "invariant_failures": failures,
        "coverage": {c: {"available": int(frame[f"direction_{c}"].notna().sum()), "improving": int(frame[f"direction_{c}"].eq(1).sum()), "deteriorating": int(frame[f"direction_{c}"].eq(-1).sum()), "unchanged": int(frame[f"direction_{c}"].eq(0).sum())} for c in LEVEL_COLUMNS},
        "authorizations": {"descriptive_representation": valid, "aggregate_recovery_score": False, "market_state_labels": False, "w01_return_screen": False, "x02_change": False, "portfolio_combination": False, "paper_trading": False, "live_trading": False},
        "interpretation_boundary": "M06 assigns per-dimension directions only. No agreement count, sign pattern, persistence rule or distribution statistic may become a market-state classifier inside M06.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": status, "period": report["period"], "invariant_failures": failures}, ensure_ascii=False, indent=2))
    if not valid:
        raise SystemExit(2)
    return report


if __name__ == "__main__":
    run()
