"""Bootstrap diagnostic for the frozen X02 next-record daily return series.

The bootstrap keeps the observed calendar span fixed so its CAGR convention is
comparable with the portfolio engine. Drawdown includes the initial 1.0 equity
point, avoiding the legacy first-day-loss blind spot.
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
MANIFEST = OUT / "execution_artifact_manifest.json"
AUDIT = OUT / "next_bar_execution_audit.json"
DAILY_NAME = "original_gate_CONSERVATIVE_next_bar_daily.csv"
DAILY = OUT / DAILY_NAME
OUTPUT_JSON = OUT / "execution_uncertainty.json"
OUTPUT_MD = OUT / "execution_uncertainty.md"
PERIOD_START = pd.Timestamp("2024-01-01")
BLOCK_LENGTH = 20
BOOTSTRAP_SAMPLES = 5000
RNG_SEED = 20260914
PRIMARY_RESULT = "original_gate_CONSERVATIVE"
PRIMARY_PERIOD = "later"
CAGR_RECONCILIATION_TOLERANCE = 1e-10


def annualized_cagr(
    returns: np.ndarray,
    periods_per_year: float = 252.0,
    *,
    elapsed_calendar_days: int | None = None,
) -> float:
    values = np.asarray(returns, dtype=float)
    if values.size == 0:
        raise ValueError("returns are empty")
    if not np.isfinite(values).all():
        raise ValueError("returns contain non-finite values")
    if np.any(values <= -1.0):
        return -1.0
    log_growth = float(np.log1p(values).sum())
    if elapsed_calendar_days is not None:
        elapsed = max(1, int(elapsed_calendar_days))
        exponent = 365.25 / elapsed
    else:
        exponent = float(periods_per_year) / values.size
    return float(np.expm1(log_growth * exponent))


def max_drawdown(returns: np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    if values.size == 0:
        raise ValueError("returns are empty")
    if not np.isfinite(values).all():
        raise ValueError("returns contain non-finite values")
    if np.any(values <= -1.0):
        return -1.0
    # Include starting cash/equity=1.0. Without this anchor, a first-day loss is
    # incorrectly treated as a new peak and can disappear from max drawdown.
    wealth = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    peak = np.maximum.accumulate(wealth)
    return float(np.min(wealth / peak - 1.0))


def moving_block_bootstrap(
    returns: np.ndarray,
    *,
    block_length: int = BLOCK_LENGTH,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = RNG_SEED,
    elapsed_calendar_days: int | None = None,
) -> dict[str, Any]:
    values = np.asarray(returns, dtype=float)
    n = int(values.size)
    if n < 2:
        raise ValueError("at least two returns are required")
    if not np.isfinite(values).all():
        raise ValueError("returns contain non-finite values")
    if block_length <= 0 or block_length > n:
        raise ValueError("invalid block_length")
    if samples <= 0:
        raise ValueError("samples must be positive")

    rng = np.random.default_rng(seed)
    max_start = n - block_length + 1
    blocks_needed = int(np.ceil(n / block_length))
    cagrs = np.empty(samples, dtype=float)
    drawdowns = np.empty(samples, dtype=float)
    for i in range(samples):
        starts = rng.integers(0, max_start, size=blocks_needed)
        sample = np.concatenate([values[s : s + block_length] for s in starts])[:n]
        cagrs[i] = annualized_cagr(sample, elapsed_calendar_days=elapsed_calendar_days)
        drawdowns[i] = max_drawdown(sample)

    annualization_basis = (
        "fixed_observed_calendar_span" if elapsed_calendar_days is not None else "252_trading_periods"
    )
    return {
        "method": "moving_block_bootstrap",
        "block_length_trading_days": int(block_length),
        "bootstrap_samples": int(samples),
        "rng_seed": int(seed),
        "n_daily_returns": n,
        "annualization_basis": annualization_basis,
        "elapsed_calendar_days": None if elapsed_calendar_days is None else int(elapsed_calendar_days),
        "observed_cagr": annualized_cagr(values, elapsed_calendar_days=elapsed_calendar_days),
        "observed_max_drawdown": max_drawdown(values),
        "cagr_probability_positive": float(np.mean(cagrs > 0.0)),
        "cagr_p05": float(np.quantile(cagrs, 0.05)),
        "cagr_p50": float(np.quantile(cagrs, 0.50)),
        "cagr_p95": float(np.quantile(cagrs, 0.95)),
        "max_drawdown_p05": float(np.quantile(drawdowns, 0.05)),
        "max_drawdown_p50": float(np.quantile(drawdowns, 0.50)),
        "max_drawdown_p95": float(np.quantile(drawdowns, 0.95)),
    }


def validate_daily_lineage(manifest: dict[str, Any], daily_path: Path = DAILY) -> dict[str, Any]:
    failures: list[str] = []
    if not bool(manifest.get("pass")):
        failures.append("execution artifact manifest did not pass")
    if not daily_path.exists():
        failures.append(f"missing {daily_path}")
        return {"pass": False, "failures": failures}
    expected = ((manifest.get("artifacts") or {}).get(DAILY_NAME) or {}).get("sha256")
    actual = sha256_file(daily_path)
    if not expected:
        failures.append("manifest lacks primary daily-series hash")
    elif expected != actual:
        failures.append("primary daily-series hash mismatch")
    return {"pass": not failures, "failures": failures, "daily_sha256": actual}


def validate_audit_lineage(manifest: dict[str, Any], audit_path: Path = AUDIT) -> dict[str, Any]:
    failures: list[str] = []
    if not audit_path.exists():
        return {"pass": False, "failures": [f"missing {audit_path}"]}
    expected = manifest.get("audit_sha256")
    actual = sha256_file(audit_path)
    if not expected:
        failures.append("execution artifact manifest lacks audit_sha256")
    elif expected != actual:
        failures.append("next-record audit hash does not match execution artifact manifest")
    return {"pass": not failures, "failures": failures, "audit_sha256": actual}


def render_markdown(result: dict[str, Any]) -> str:
    def pct(value: object) -> str:
        try:
            return f"{float(value):.2%}"
        except (TypeError, ValueError):
            return "n/a"

    s = result.get("statistics", {})
    reconciliation = result.get("cagr_reconciliation", {})
    return "\n".join([
        "# X02 execution uncertainty diagnostic",
        "",
        f"- Observed CAGR: {pct(s.get('observed_cagr'))}",
        f"- Audit-reported CAGR: {pct(reconciliation.get('audit_reported_cagr'))}",
        f"- Bootstrap probability CAGR > 0: {pct(s.get('cagr_probability_positive'))}",
        f"- CAGR 5th / 50th / 95th percentile: {pct(s.get('cagr_p05'))} / {pct(s.get('cagr_p50'))} / {pct(s.get('cagr_p95'))}",
        f"- Observed corrected max drawdown: {pct(s.get('observed_max_drawdown'))}",
        f"- Corrected max-drawdown 5th / 50th / 95th percentile: {pct(s.get('max_drawdown_p05'))} / {pct(s.get('max_drawdown_p50'))} / {pct(s.get('max_drawdown_p95'))}",
        f"- Annualization basis: `{s.get('annualization_basis', 'n/a')}`",
        f"- Observed calendar span: {s.get('elapsed_calendar_days', 'n/a')} days",
        f"- Block length: {s.get('block_length_trading_days', 'n/a')} trading days",
        f"- Bootstrap samples: {s.get('bootstrap_samples', 'n/a')}",
        "",
        "Drawdown in this diagnostic includes the initial 1.0 equity point. This intentionally fixes the legacy metric's first-day-loss blind spot; comparison reports retain the legacy drawdown definition only for apples-to-apples historical comparison.",
        "",
        "This is a sampling-uncertainty diagnostic of the frozen historical return path; it is not an out-of-sample test.",
        "",
    ])


def main() -> None:
    if not MANIFEST.exists():
        raise SystemExit("run bind_x02_execution_artifacts.py first")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    daily_lineage = validate_daily_lineage(manifest)
    audit_lineage = validate_audit_lineage(manifest)
    failures = list(daily_lineage.get("failures", [])) + list(audit_lineage.get("failures", []))
    if failures:
        raise SystemExit("uncertainty lineage validation failed: " + "; ".join(failures))

    frame = pd.read_csv(DAILY, index_col=0, parse_dates=True)
    if frame.empty:
        raise SystemExit("primary daily series is empty")
    values = pd.to_numeric(frame.iloc[:, 0], errors="coerce")
    values.index = pd.to_datetime(values.index).normalize()
    later = values[values.index >= PERIOD_START]
    if later.isna().any():
        raise SystemExit("primary daily series contains non-numeric rows")
    if len(later) < BLOCK_LENGTH:
        raise SystemExit(f"need at least {BLOCK_LENGTH} daily returns in 2024+ period")

    elapsed_days = max(1, int((later.index[-1] - later.index[0]).days))
    statistics = moving_block_bootstrap(
        later.to_numpy(dtype=float),
        elapsed_calendar_days=elapsed_days,
    )

    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    audit_cagr = (
        ((audit.get("results") or {}).get(PRIMARY_RESULT) or {}).get(PRIMARY_PERIOD) or {}
    ).get("cagr")
    if audit_cagr is None:
        raise SystemExit(f"next-record audit lacks {PRIMARY_RESULT}/{PRIMARY_PERIOD} CAGR")
    cagr_difference = float(statistics["observed_cagr"]) - float(audit_cagr)
    if abs(cagr_difference) > CAGR_RECONCILIATION_TOLERANCE:
        raise SystemExit(
            "uncertainty CAGR does not reconcile to next-record audit: "
            f"observed={statistics['observed_cagr']}, audit={audit_cagr}, delta={cagr_difference}"
        )

    result = {
        "analysis": "X02_EXECUTION_UNCERTAINTY_V2",
        "primary_spec": PRIMARY_RESULT,
        "period": PRIMARY_PERIOD,
        "period_start": str(PERIOD_START.date()),
        "descriptive_only": True,
        "parameter_search": False,
        "lineage": {
            "pass": True,
            "daily": daily_lineage,
            "audit": audit_lineage,
        },
        "cagr_reconciliation": {
            "pass": True,
            "audit_reported_cagr": float(audit_cagr),
            "bootstrap_observed_cagr": float(statistics["observed_cagr"]),
            "difference": cagr_difference,
            "tolerance": CAGR_RECONCILIATION_TOLERANCE,
        },
        "statistics": statistics,
        "interpretation_boundary": (
            "Bootstrap dispersion reflects resampling uncertainty in the observed frozen path only and does not account for model-selection bias or regime change."
        ),
    }
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(render_markdown(result), encoding="utf-8")
    print(render_markdown(result))


if __name__ == "__main__":
    main()
