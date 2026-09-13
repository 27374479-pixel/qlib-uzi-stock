"""Deterministic moving-block bootstrap diagnostics for frozen X02 execution returns.

This stage is descriptive only. It does not search parameters, change the
strategy, or authorize live trading. It quantifies sampling uncertainty around
the already-frozen 2024+ CONSERVATIVE next-record daily return series while
preserving short-run serial dependence with fixed-length moving blocks.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "x02_reproduction_20260912"
AUDIT = OUT / "next_bar_execution_audit.json"
DAILY = OUT / "original_gate_CONSERVATIVE_next_bar_daily.csv"
OUTPUT_JSON = OUT / "execution_uncertainty.json"
OUTPUT_MD = OUT / "execution_uncertainty.md"
PERIOD_START = pd.Timestamp("2024-01-01")
BLOCK_LENGTH = 20
BOOTSTRAP_SAMPLES = 5000
RNG_SEED = 20260914


def annualized_cagr(returns: np.ndarray, periods_per_year: float = 252.0) -> float:
    values = np.asarray(returns, dtype=float)
    if values.size == 0:
        raise ValueError("returns are empty")
    if not np.isfinite(values).all():
        raise ValueError("returns contain non-finite values")
    if np.any(values <= -1.0):
        return -1.0
    log_growth = float(np.log1p(values).sum())
    return float(np.expm1(log_growth * periods_per_year / values.size))


def max_drawdown(returns: np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    if values.size == 0:
        raise ValueError("returns are empty")
    wealth = np.cumprod(1.0 + values)
    peak = np.maximum.accumulate(wealth)
    return float(np.min(wealth / peak - 1.0))


def moving_block_bootstrap(
    returns: np.ndarray,
    *,
    block_length: int = BLOCK_LENGTH,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = RNG_SEED,
) -> dict[str, Any]:
    values = np.asarray(returns, dtype=float)
    n = int(values.size)
    if n < 2:
        raise ValueError("at least two daily returns are required")
    if not np.isfinite(values).all():
        raise ValueError("returns contain non-finite values")
    if block_length <= 0 or block_length > n:
        raise ValueError("block_length must be between 1 and sample length")
    if samples <= 0:
        raise ValueError("samples must be positive")

    rng = np.random.default_rng(seed)
    starts_max = n - block_length + 1
    blocks_needed = int(np.ceil(n / block_length))
    cagrs = np.empty(samples, dtype=float)
    drawdowns = np.empty(samples, dtype=float)

    for i in range(samples):
        starts = rng.integers(0, starts_max, size=blocks_needed)
        resampled = np.concatenate([values[s : s + block_length] for s in starts])[:n]
        cagrs[i] = annualized_cagr(resampled)
        drawdowns[i] = max_drawdown(resampled)

    return {
        "method": "moving_block_bootstrap",
        "block_length_trading_days": int(block_length),
        "bootstrap_samples": int(samples),
        "rng_seed": int(seed),
        "n_daily_returns": n,
        "observed_cagr": annualized_cagr(values),
        "observed_max_drawdown": max_drawdown(values),
        "cagr_probability_positive": float(np.mean(cagrs > 0.0)),
        "cagr_p05": float(np.quantile(cagrs, 0.05)),
        "cagr_p50": float(np.quantile(cagrs, 0.50)),
        "cagr_p95": float(np.quantile(cagrs, 0.95)),
        "max_drawdown_p05": float(np.quantile(drawdowns, 0.05)),
        "max_drawdown_p50": float(np.quantile(drawdowns, 0.50)),
        "max_drawdown_p95": float(np.quantile(drawdowns, 0.95)),
    }


def validate_daily_lineage(audit: dict[str, Any], daily_path: Path = DAILY) -> dict[str, Any]:
    failures: list[str] = []
    if not daily_path.exists():
        failures.append(f"missing {daily_path}")
        return {"pass": False, "failures": failures}

    inputs = audit.get("inputs") or {}
    if not inputs.get("pass"):
        failures.append("next-record audit input lineage did not pass")

    artifact = ((audit.get("artifacts") or {}).get("original_gate_CONSERVATIVE") or {}).get("daily") or {}
    expected = artifact.get("sha256")
    actual = sha256_file(daily_path)
    if not expected:
        failures.append("next-record audit lacks primary daily-series hash; rerun audit with current code")
    elif expected != actual:
        failures.append("primary next-record daily-series hash does not match audit artifact record")
    return {"pass": not failures, "failures": failures, "daily_sha256": actual}


def render_markdown(result: dict[str, Any]) -> str:
    def pct(value: object) -> str:
        try:
            return f"{float(value):.2%}"
        except (TypeError, ValueError):
            return "n/a"

    stats = result.get("statistics", {})
    return "\n".join([
        "# X02 execution uncertainty diagnostic",
        "",
        "Moving-block bootstrap of the frozen `original_gate_CONSERVATIVE` next-record daily returns from 2024 onward.",
        "",
        f"- Observed CAGR: {pct(stats.get('observed_cagr'))}",
        f"- Bootstrap probability CAGR > 0: {pct(stats.get('cagr_probability_positive'))}",
        f"- CAGR 5th / 50th / 95th percentile: {pct(stats.get('cagr_p05'))} / {pct(stats.get('cagr_p50'))} / {pct(stats.get('cagr_p95'))}",
        f"- Observed max drawdown: {pct(stats.get('observed_max_drawdown'))}",
        f"- Max-drawdown 5th / 50th / 95th percentile: {pct(stats.get('max_drawdown_p05'))} / {pct(stats.get('max_drawdown_p50'))} / {pct(stats.get('max_drawdown_p95'))}",
        f"- Block length: {stats.get('block_length_trading_days', 'n/a')} trading days",
        f"- Bootstrap samples: {stats.get('bootstrap_samples', 'n/a')}",
        "",
        "This is a sampling-uncertainty diagnostic, not pristine OOS evidence and not a parameter-selection rule.",
        "",
    ])


def main() -> None:
    if not AUDIT.exists():
        raise SystemExit("run audit_x02_next_bar_execution.py first")
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    lineage = validate_daily_lineage(audit)
    if not lineage["pass"]:
        raise SystemExit("uncertainty lineage validation failed: " + "; ".join(lineage["failures"]))

    frame = pd.read_csv(DAILY, index_col=0, parse_dates=True)
    if frame.empty:
        raise SystemExit("primary next-record daily series is empty")
    values = pd.to_numeric(frame.iloc[:, 0], errors="coerce")
    values.index = pd.to_datetime(values.index).normalize()
    later = values[values.index >= PERIOD_START]
    if later.isna().any():
        raise SystemExit("primary next-record daily series contains non-numeric rows")
    if len(later) < BLOCK_LENGTH:
        raise SystemExit(f"need at least {BLOCK_LENGTH} daily returns in 2024+ period")

    result = {
        "analysis": "X02_EXECUTION_UNCERTAINTY_V1",
        "primary_spec": "original_gate_CONSERVATIVE",
        "period": "later",
        "period_start": str(PERIOD_START.date()),
        "descriptive_only": True,
        "parameter_search": False,
        "live_trading_authorized": False,
        "lineage": lineage,
        "statistics": moving_block_bootstrap(later.to_numpy(dtype=float)),
        "interpretation_boundary": (
            "Bootstrap dispersion quantifies resampling uncertainty in the observed frozen return path only; it does not account for model-selection bias, regime change, or guarantee future profitability."
        ),
    }
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(render_markdown(result), encoding="utf-8")
    print(render_markdown(result))


if __name__ == "__main__":
    main()
