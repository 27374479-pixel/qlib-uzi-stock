"""M06 non-P&L validation of a common source-grounded recovery factor.

The factor is fit only on development-period M05 market-tape changes. Reserved
prior-strong-stock behavior is used only for non-strategy validation.
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
from v5_m05_recovery_dynamics import build_recovery_dynamics
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
PREREG = ROOT / "V5_M06_RECOVERY_FACTOR_PREREG.md"
M05_RESULT = ROOT / "V5_M05_RESULT.md"
OUT = ROOT / "output" / "v5_m06_recovery_factor_validation"
REPORT = OUT / "report.json"
SCORES = OUT / "recovery_factor_scores.parquet"

START = "2021-05-17"
END = "2026-09-03"
DEV_END = pd.Timestamp("2023-12-31")
LATER_START = pd.Timestamp("2024-01-01")
BOOT_BLOCK = 20
BOOT_DRAWS = 5000
BOOT_SEED = 20260915

ORIENTED_FEATURES = {
    "delta_advance_ratio": 1.0,
    "delta_decline_ratio": -1.0,
    "delta_limit_down_ratio": -1.0,
    "delta_seal_ratio": 1.0,
    "delta_broken_ratio": -1.0,
    "delta_multi_board_ratio": 1.0,
    "delta_positive_industry_ratio": 1.0,
    "delta_seal_industry_ratio": 1.0,
    "delta_first_board_industry_ratio": 1.0,
    "delta_multi_board_industry_ratio": 1.0,
    "delta_seal_hhi": -1.0,
    "delta_first_board_hhi": -1.0,
    "delta_multi_board_hhi": -1.0,
}
VALIDATORS = (
    "delta_prior_seal_mean_return",
    "delta_prior_multi_board_mean_return",
)

CONTRACT = {
    "version": "V5_M06_RECOVERY_FACTOR_VALIDATION_V1",
    "mode": "NON_PNL_REPRESENTATION_VALIDATION",
    "development_end": str(DEV_END.date()),
    "historical_later_start": str(LATER_START.date()),
    "primary_features": ORIENTED_FEATURES,
    "reserved_validators": list(VALIDATORS),
    "bootstrap_block_sessions": BOOT_BLOCK,
    "bootstrap_draws": BOOT_DRAWS,
    "bootstrap_seed": BOOT_SEED,
    "strategy_returns_used": False,
    "parameter_search": False,
    "state_labels_authorized": False,
    "factor_threshold_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def orient_primary(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({"date": pd.to_datetime(frame["date"]).dt.normalize()})
    for column, sign in ORIENTED_FEATURES.items():
        if column not in frame.columns:
            raise RuntimeError(f"M06 missing primary feature: {column}")
        out[column] = pd.to_numeric(frame[column], errors="coerce") * sign
    for column in VALIDATORS:
        if column not in frame.columns:
            raise RuntimeError(f"M06 missing validator: {column}")
        out[column] = pd.to_numeric(frame[column], errors="coerce")
    return out


def fit_development_pc1(oriented: pd.DataFrame) -> dict[str, Any]:
    feature_names = list(ORIENTED_FEATURES)
    dev = oriented.loc[oriented["date"] <= DEV_END, feature_names].dropna().copy()
    if len(dev) < 2:
        raise RuntimeError("M06 development sample too small")
    mean = dev.mean(axis=0)
    std = dev.std(axis=0, ddof=0)
    if (~np.isfinite(std.to_numpy(float))).any() or (std <= 0).any():
        raise RuntimeError("M06 development feature has zero/nonfinite standard deviation")
    z = (dev - mean) / std
    _, singular, vt = np.linalg.svd(z.to_numpy(float), full_matrices=False)
    loadings = vt[0].astype(float)
    if float(loadings.sum()) < 0:
        loadings *= -1.0
    var = np.square(singular)
    explained = float(var[0] / var.sum()) if float(var.sum()) > 0 else float("nan")
    return {
        "feature_names": feature_names,
        "mean": mean.to_numpy(float),
        "std": std.to_numpy(float),
        "loadings": loadings,
        "explained_variance_ratio": explained,
        "development_rows": int(len(dev)),
    }


def score_with_frozen_pc(oriented: pd.DataFrame, model: dict[str, Any]) -> pd.Series:
    names = model["feature_names"]
    x = oriented[names].to_numpy(float)
    mean = np.asarray(model["mean"], dtype=float)
    std = np.asarray(model["std"], dtype=float)
    loadings = np.asarray(model["loadings"], dtype=float)
    complete = np.isfinite(x).all(axis=1)
    scores = np.full(len(oriented), np.nan, dtype=float)
    scores[complete] = ((x[complete] - mean) / std) @ loadings
    return pd.Series(scores, index=oriented.index, dtype=float)


def spearman_corr(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    if int(mask.sum()) < 3:
        return float("nan")
    xr = pd.Series(x[mask]).rank(method="average").to_numpy(float)
    yr = pd.Series(y[mask]).rank(method="average").to_numpy(float)
    if np.std(xr) == 0 or np.std(yr) == 0:
        return float("nan")
    return float(np.corrcoef(xr, yr)[0, 1])


def moving_block_bootstrap_spearman(
    x: np.ndarray,
    y: np.ndarray,
    *,
    block: int = BOOT_BLOCK,
    draws: int = BOOT_DRAWS,
    seed: int = BOOT_SEED,
) -> dict[str, Any]:
    if len(x) != len(y):
        raise ValueError("M06 bootstrap arrays must have equal length")
    n = len(x)
    observed = spearman_corr(x, y)
    if n < 3 or not np.isfinite(observed):
        return {"n_sessions": n, "paired_n": int((np.isfinite(x) & np.isfinite(y)).sum()), "observed": None, "ci95_low": None, "ci95_high": None, "valid_draws": 0}

    rng = np.random.default_rng(seed)
    block = max(1, min(int(block), n))
    starts = np.arange(0, n - block + 1)
    samples: list[float] = []
    blocks_needed = int(np.ceil(n / block))
    for _ in range(int(draws)):
        chosen = rng.choice(starts, size=blocks_needed, replace=True)
        idx = np.concatenate([np.arange(s, s + block) for s in chosen])[:n]
        value = spearman_corr(x[idx], y[idx])
        if np.isfinite(value):
            samples.append(float(value))
    if not samples:
        return {"n_sessions": n, "paired_n": int((np.isfinite(x) & np.isfinite(y)).sum()), "observed": observed, "ci95_low": None, "ci95_high": None, "valid_draws": 0}
    arr = np.asarray(samples, dtype=float)
    return {
        "n_sessions": n,
        "paired_n": int((np.isfinite(x) & np.isfinite(y)).sum()),
        "observed": observed,
        "ci95_low": float(np.quantile(arr, 0.025)),
        "ci95_high": float(np.quantile(arr, 0.975)),
        "valid_draws": int(len(arr)),
    }


def evaluate(oriented: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    model = fit_development_pc1(oriented)
    scored = oriented.copy()
    scored["recovery_factor"] = score_with_frozen_pc(oriented, model)

    loadings = {name: float(value) for name, value in zip(model["feature_names"], model["loadings"])}
    all_positive = all(value > 0 for value in loadings.values())

    validation: dict[str, Any] = {}
    gates = [all_positive]
    partitions = {
        "development": scored["date"] <= DEV_END,
        "historical_later": scored["date"] >= LATER_START,
    }
    seed_offset = 0
    for partition_name, mask in partitions.items():
        validation[partition_name] = {}
        subset = scored.loc[mask].reset_index(drop=True)
        for validator in VALIDATORS:
            stats = moving_block_bootstrap_spearman(
                subset["recovery_factor"].to_numpy(float),
                subset[validator].to_numpy(float),
                seed=BOOT_SEED + seed_offset,
            )
            seed_offset += 1
            validation[partition_name][validator] = stats
            gates.append(
                stats["observed"] is not None
                and stats["observed"] > 0
                and stats["ci95_low"] is not None
                and stats["ci95_low"] > 0
            )

    supported = bool(all(gates))
    result = {
        "status": "SUPPORTED_AS_COMMON_RECOVERY_FACTOR" if supported else "NOT_SUPPORTED_AS_COMMON_RECOVERY_FACTOR",
        "supported": supported,
        "model": {
            "development_rows": model["development_rows"],
            "explained_variance_ratio": model["explained_variance_ratio"],
            "loadings": loadings,
            "all_oriented_loadings_strictly_positive": all_positive,
            "mean": {name: float(v) for name, v in zip(model["feature_names"], model["mean"])},
            "std": {name: float(v) for name, v in zip(model["feature_names"], model["std"])},
        },
        "validator_results": validation,
        "authorizations": {
            "continuous_descriptive_factor": supported,
            "market_state_labels": False,
            "factor_threshold": False,
            "w01_return_screen": False,
            "x02_change": False,
            "portfolio_combination": False,
            "paper_trading": False,
            "live_trading": False,
        },
    }
    return scored, result


def run() -> dict[str, Any]:
    for path in (PREREG, M05_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)

    panel, metadata = load_panel(EventConfig(universe="csi800", start=START, end=END))
    tape = build_market_tape(panel)
    dispersion = build_dispersion(panel)
    dynamics = build_recovery_dynamics(tape, dispersion)
    oriented = orient_primary(dynamics)
    scored, result = evaluate(oriented)

    OUT.mkdir(parents=True, exist_ok=True)
    scored.to_parquet(SCORES, index=False, compression="zstd")
    report = {
        "contract": CONTRACT,
        "lineage": {
            "prereg_sha256": sha256_file(PREREG),
            "m05_result_sha256": sha256_file(M05_RESULT),
        },
        "panel_metadata": metadata,
        "period": {
            "start": str(scored["date"].min().date()),
            "end": str(scored["date"].max().date()),
            "dates": int(len(scored)),
        },
        **result,
        "interpretation_boundary": (
            "M06 tests only whether a development-fitted, source-oriented common recovery factor is supported by reserved non-strategy market behavior in both time partitions. "
            "It never defines a tradable state or score threshold."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "model": report["model"], "validator_results": report["validator_results"], "authorizations": report["authorizations"]}, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
