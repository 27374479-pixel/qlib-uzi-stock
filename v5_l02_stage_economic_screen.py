"""One-shot economic test for the frozen L01 leader-stage representation.

L02 is preregistered before any L02 return result is computed.  It compares the
book-named/frozen L01 `confirmation` proxy with the frozen L01 `disagreement`
proxy using the repository's existing next-open executable return machinery.

A pass authorizes only a separately specified execution validation.  This file
does not authorize parameter search, stage-pair search, portfolio combination,
paper trading, or live trading.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import book_alpha_daily_screen as core
import v5_b01_leader_disagreement_screen as b01
import v5_l01_leader_stage_transition_audit as l01
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
PREREG = ROOT / "V5_L02_STAGE_ECONOMIC_PREREGISTRATION.md"
L01_SPEC = ROOT / "V5_L01_LEADER_STAGE_PROXY_SPEC.md"
OUT = ROOT / "output" / "v5_l02_stage_economic"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "observations.parquet"

START = pd.Timestamp("2021-05-17")
DEV_END = pd.Timestamp("2023-12-31")
LATER_START = pd.Timestamp("2024-01-01")
ROUND_TRIP_COST = 0.0036
BOOTSTRAP_SAMPLES = 5000
SEED = 20260914
PRIMARY_HORIZON = 2

MIN_CONFIRMATION_N = 50
MIN_CONFIRMATION_DAYS = 30
MIN_DISAGREEMENT_N = 30
MIN_DISAGREEMENT_DAYS = 20
MIN_PAIRED_DAYS = 20

CONTRACT = {
    "version": "V5_L02_STAGE_ECONOMIC_V1",
    "source": "user-supplied lower 48-trader volume, PDF page 123/227 (printed p.92)",
    "representation_dependency": l01.CONTRACT["version"],
    "selected_stage": "confirmation",
    "control_stage": "disagreement",
    "expected_direction": "confirmation > disagreement",
    "entry": "next available open; next session locked at upper limit is unfilled",
    "primary_horizon_trading_days": PRIMARY_HORIZON,
    "diagnostic_horizons_trading_days": [1, 5],
    "round_trip_cost": ROUND_TRIP_COST,
    "bootstrap_samples": BOOTSTRAP_SAMPLES,
    "seed": SEED,
    "development": [str(START.date()), str(DEV_END.date())],
    "historical_later_start": str(LATER_START.date()),
    "sample_gates": {
        "confirmation_executable_n": MIN_CONFIRMATION_N,
        "confirmation_active_days": MIN_CONFIRMATION_DAYS,
        "disagreement_executable_n": MIN_DISAGREEMENT_N,
        "disagreement_active_days": MIN_DISAGREEMENT_DAYS,
        "paired_days": MIN_PAIRED_DAYS,
    },
    "parameter_search": False,
    "stage_pair_search": False,
    "x02_retuning": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def screen_config() -> core.ScreenConfig:
    """Reuse the established V5 point-in-time daily execution conventions."""
    return core.ScreenConfig(
        universe="csi800",
        start="2015-01-01",
        end="2026-09-03",
        oos_start=str(LATER_START.date()),
        round_trip_cost=ROUND_TRIP_COST,
        bootstrap_samples=BOOTSTRAP_SAMPLES,
        seed=SEED,
        min_oos_observations=MIN_CONFIRMATION_N,
        min_oos_days=MIN_CONFIRMATION_DAYS,
        output=str(REPORT.relative_to(ROOT)),
        observations_output=str(OBSERVATIONS.relative_to(ROOT)),
    )


def segment(frame: pd.DataFrame, which: str) -> pd.DataFrame:
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if which == "development_2021_2023":
        return frame.loc[dates.between(START, DEV_END)].copy()
    if which == "historical_later_2024_plus":
        return frame.loc[dates.ge(LATER_START)].copy()
    raise ValueError(which)


def cohorts(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "stage_proxy" not in frame:
        raise RuntimeError("L02 frame is missing frozen L01 stage_proxy")
    selected = frame.loc[frame["stage_proxy"].eq(CONTRACT["selected_stage"])].copy()
    control = frame.loc[frame["stage_proxy"].eq(CONTRACT["control_stage"])].copy()
    if set(selected.index).intersection(control.index):
        raise RuntimeError("L02 selected/control cohorts overlap")
    return selected, control


def evaluate_period(
    selected: pd.DataFrame,
    control: pd.DataFrame,
    config: core.ScreenConfig,
    seed_offset: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for horizon in (1, 2, 5):
        out[f"{horizon}d"] = {
            "selected": core.sample_metrics(selected, horizon, config, seed_offset + horizon),
            "control": core.sample_metrics(control, horizon, config, seed_offset + horizon + 10),
            "paired": core.paired_difference(
                selected,
                control,
                horizon,
                1,
                config,
                seed_offset + horizon + 20,
            ),
        }
    return out


def qualification_from_primary(
    development: dict[str, Any], historical_later: dict[str, Any]
) -> dict[str, Any]:
    insufficient: list[str] = []
    failures: list[str] = []
    for label, primary in (
        ("development_2021_2023", development),
        ("historical_later_2024_plus", historical_later),
    ):
        selected = primary.get("selected", {})
        control = primary.get("control", {})
        paired = primary.get("paired", {})

        if int(selected.get("n", 0)) < MIN_CONFIRMATION_N:
            insufficient.append(f"{label}: executable confirmation observations < {MIN_CONFIRMATION_N}")
        if int(selected.get("active_days", 0)) < MIN_CONFIRMATION_DAYS:
            insufficient.append(f"{label}: active confirmation dates < {MIN_CONFIRMATION_DAYS}")
        if int(control.get("n", 0)) < MIN_DISAGREEMENT_N:
            insufficient.append(f"{label}: executable disagreement observations < {MIN_DISAGREEMENT_N}")
        if int(control.get("active_days", 0)) < MIN_DISAGREEMENT_DAYS:
            insufficient.append(f"{label}: active disagreement dates < {MIN_DISAGREEMENT_DAYS}")
        if int(paired.get("paired_days", 0)) < MIN_PAIRED_DAYS:
            insufficient.append(f"{label}: paired confirmation/disagreement dates < {MIN_PAIRED_DAYS}")

        mean_return = selected.get("mean_return")
        if mean_return is None or not np.isfinite(mean_return) or float(mean_return) <= 0:
            failures.append(f"{label}: confirmation 2d mean net return is not positive")
        mean_excess = selected.get("mean_market_excess")
        if mean_excess is None or not np.isfinite(mean_excess) or float(mean_excess) <= 0:
            failures.append(f"{label}: confirmation 2d mean market excess is not positive")
        diff = paired.get("expected_signed_difference")
        if diff is None or not np.isfinite(diff) or float(diff) <= 0:
            failures.append(f"{label}: confirmation-minus-disagreement 2d difference is not positive")
        ci = paired.get("bootstrap95_expected_signed_difference") or [None, None]
        lower = ci[0] if len(ci) else None
        if lower is None or not np.isfinite(lower) or float(lower) <= 0:
            failures.append(
                f"{label}: paired 2d bootstrap 95% lower bound is not above zero"
            )

    if insufficient:
        status = "INSUFFICIENT"
        reasons = insufficient + failures
    elif failures:
        status = "REJECTED"
        reasons = failures
    else:
        status = "QUALIFIED_FOR_EXECUTION_VALIDATION_ONLY"
        reasons = ["all preregistered L02 primary 2d conditions passed"]
    return {
        "status": status,
        "qualified_for_execution_validation": status == "QUALIFIED_FOR_EXECUTION_VALIDATION_ONLY",
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "reasons": reasons,
    }


def _diagnostics(sample: pd.DataFrame, config: core.ScreenConfig, seed_base: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "weak_market" in sample:
        weak = sample["weak_market"].fillna(False).astype(bool)
        result["weak_market_2d"] = core.sample_metrics(
            sample.loc[weak], PRIMARY_HORIZON, config, seed_base + 1
        )
        result["non_weak_market_2d"] = core.sample_metrics(
            sample.loc[~weak], PRIMARY_HORIZON, config, seed_base + 2
        )
    yearly: dict[str, Any] = {}
    years = pd.to_datetime(sample["date"], errors="coerce").dt.year
    for year in sorted(years.dropna().unique()):
        yearly[str(int(year))] = core.sample_metrics(
            sample.loc[years.eq(year)], PRIMARY_HORIZON, config, seed_base + 100 + int(year) % 100
        )
    result["yearly_2d"] = yearly
    return result


def prepare_frame(config: core.ScreenConfig) -> pd.DataFrame:
    """Attach returns first, then apply the untouched L01 point-in-time labels."""
    with_returns = b01.prepare_frame(config)
    labelled = l01.annotate_stages(with_returns)
    dates = pd.to_datetime(labelled["date"], errors="coerce")
    return labelled.loc[dates.ge(START)].copy()


def run() -> dict[str, Any]:
    if not PREREG.exists():
        raise FileNotFoundError(PREREG)
    if not L01_SPEC.exists():
        raise FileNotFoundError(L01_SPEC)

    config = screen_config()
    frame = prepare_frame(config)
    selected, control = cohorts(frame)

    periods: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    for idx, name in enumerate(("development_2021_2023", "historical_later_2024_plus")):
        s = segment(selected, name)
        c = segment(control, name)
        periods[name] = evaluate_period(s, c, config, 1000 + idx * 200)
        diagnostics[name] = {
            "confirmation": _diagnostics(s, config, 3000 + idx * 500),
            "disagreement": _diagnostics(c, config, 4000 + idx * 500),
        }

    primary_dev = periods["development_2021_2023"][f"{PRIMARY_HORIZON}d"]
    primary_later = periods["historical_later_2024_plus"][f"{PRIMARY_HORIZON}d"]
    qualification = qualification_from_primary(primary_dev, primary_later)

    OUT.mkdir(parents=True, exist_ok=True)
    observation_columns = [
        "date",
        "instrument",
        "entry_date",
        "entry_filled",
        "seal_bool",
        "board_num",
        "stage_proxy",
        "weak_market",
        "return_1d",
        "return_2d",
        "return_5d",
        "market_excess_1d",
        "market_excess_2d",
        "market_excess_5d",
    ]
    observation_columns = [c for c in observation_columns if c in frame.columns]
    obs_parts: list[pd.DataFrame] = []
    for label, cohort in (("confirmation", selected), ("disagreement", control)):
        if cohort.empty:
            continue
        item = cohort[observation_columns].copy()
        item["cohort"] = label
        obs_parts.append(item)
    if obs_parts:
        pd.concat(obs_parts, ignore_index=True).to_parquet(
            OBSERVATIONS, index=False, compression="zstd"
        )

    def _count(sample: pd.DataFrame) -> dict[str, Any]:
        filled = sample["entry_filled"].fillna(False).astype(bool)
        return {
            "signals": int(len(sample)),
            "active_dates": int(sample["date"].nunique()),
            "executable": int(filled.sum()),
            "executable_active_dates": int(sample.loc[filled, "date"].nunique()),
            "fill_rate": float(filled.mean()) if len(sample) else None,
        }

    report = {
        "contract": CONTRACT,
        "preregistration_sha256": sha256_file(PREREG),
        "l01_spec_sha256": sha256_file(L01_SPEC),
        "l01_contract_version": l01.CONTRACT["version"],
        "counts": {
            "confirmation": _count(selected),
            "disagreement": _count(control),
        },
        "periods": periods,
        "diagnostics": diagnostics,
        "primary_qualification": qualification,
        "interpretation_boundary": (
            "L02 is a one-shot economic test of the preregistered confirmation-vs-disagreement "
            "operational hypothesis. A pass permits only separately specified execution validation; "
            "a failure/insufficient result cannot be rescued by changing stages, horizons, costs, or thresholds."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": qualification["status"],
                "counts": report["counts"],
                "development_2d": primary_dev,
                "historical_later_2d": primary_later,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        flush=True,
    )
    return report


if __name__ == "__main__":
    run()
