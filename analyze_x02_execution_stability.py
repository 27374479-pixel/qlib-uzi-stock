"""Deterministic regime-stability diagnostics for frozen X02 execution returns.

This stage is descriptive only. It does not search parameters or change the
strategy. It reports calendar-year and fixed rolling-window compounded returns
for the already-frozen 2024+ CONSERVATIVE next-record daily series.
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
DAILY_NAME = "original_gate_CONSERVATIVE_next_bar_daily.csv"
DAILY = OUT / DAILY_NAME
OUTPUT_JSON = OUT / "execution_stability.json"
OUTPUT_MD = OUT / "execution_stability.md"
PERIOD_START = pd.Timestamp("2024-01-01")
ROLLING_WINDOWS = (126, 252)


def compounded_return(values: np.ndarray) -> float:
    x = np.asarray(values, dtype=float)
    if x.size == 0:
        raise ValueError("returns are empty")
    if not np.isfinite(x).all():
        raise ValueError("returns contain non-finite values")
    if np.any(x <= -1.0):
        return -1.0
    return float(np.expm1(np.log1p(x).sum()))


def rolling_compounded(series: pd.Series, window: int) -> pd.Series:
    if window <= 0:
        raise ValueError("window must be positive")
    s = pd.to_numeric(series, errors="coerce")
    if s.isna().any():
        raise ValueError("returns contain non-numeric values")
    if len(s) < window:
        return pd.Series(dtype=float, name=f"rolling_{window}")
    logged = np.log1p(s.astype(float))
    out = np.expm1(logged.rolling(window=window, min_periods=window).sum()).dropna()
    out.name = f"rolling_{window}"
    return out


def summarize_rolling(series: pd.Series, window: int) -> dict[str, Any]:
    r = rolling_compounded(series, window)
    if r.empty:
        return {
            "window_trading_days": int(window),
            "n_windows": 0,
            "positive_fraction": None,
            "worst": None,
            "p10": None,
            "median": None,
            "p90": None,
            "best": None,
        }
    return {
        "window_trading_days": int(window),
        "n_windows": int(len(r)),
        "positive_fraction": float((r > 0).mean()),
        "worst": float(r.min()),
        "p10": float(r.quantile(0.10)),
        "median": float(r.median()),
        "p90": float(r.quantile(0.90)),
        "best": float(r.max()),
    }


def calendar_year_returns(series: pd.Series) -> dict[str, float]:
    result: dict[str, float] = {}
    for year, values in series.groupby(series.index.year):
        result[str(int(year))] = compounded_return(values.to_numpy(dtype=float))
    return result


def analyze_stability(series: pd.Series) -> dict[str, Any]:
    s = pd.to_numeric(series, errors="coerce")
    if s.empty:
        raise ValueError("returns are empty")
    if s.isna().any():
        raise ValueError("returns contain non-numeric values")
    s.index = pd.to_datetime(s.index).normalize()
    years = calendar_year_returns(s)
    return {
        "n_daily_returns": int(len(s)),
        "first_date": str(s.index.min().date()),
        "last_date": str(s.index.max().date()),
        "active_day_fraction": float(s.ne(0).mean()),
        "calendar_year_returns": years,
        "positive_calendar_year_fraction": float(sum(v > 0 for v in years.values()) / len(years)) if years else None,
        "last_calendar_year_is_partial": bool(s.index.max().month < 12 or s.index.max().day < 31),
        "rolling_windows": {str(window): summarize_rolling(s, window) for window in ROLLING_WINDOWS},
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


def render_markdown(result: dict[str, Any]) -> str:
    def pct(value: object) -> str:
        try:
            return f"{float(value):.2%}"
        except (TypeError, ValueError):
            return "n/a"

    stats = result.get("statistics", {})
    lines = [
        "# X02 execution stability diagnostic",
        "",
        "Frozen `original_gate_CONSERVATIVE` next-record daily returns from 2024 onward.",
        "",
        "## Calendar years",
        "",
    ]
    for year, value in (stats.get("calendar_year_returns") or {}).items():
        suffix = " (partial)" if year == str(pd.Timestamp(stats.get("last_date")).year) and stats.get("last_calendar_year_is_partial") else ""
        lines.append(f"- {year}{suffix}: {pct(value)}")
    lines.extend(["", "## Fixed rolling windows", ""])
    for window, row in (stats.get("rolling_windows") or {}).items():
        lines.append(
            f"- {window} trading days: positive {pct(row.get('positive_fraction'))}; "
            f"worst {pct(row.get('worst'))}; P10 {pct(row.get('p10'))}; "
            f"median {pct(row.get('median'))}; P90 {pct(row.get('p90'))}; best {pct(row.get('best'))} "
            f"({row.get('n_windows', 0)} windows)"
        )
    lines.extend([
        "",
        "The 126/252-day windows were fixed before reading the local execution result. This diagnostic describes path stability only; it is not a new gate, parameter search, or future-return guarantee.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    if not MANIFEST.exists():
        raise SystemExit("run bind_x02_execution_artifacts.py first")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    lineage = validate_daily_lineage(manifest)
    if not lineage["pass"]:
        raise SystemExit("stability lineage validation failed: " + "; ".join(lineage["failures"]))

    frame = pd.read_csv(DAILY, index_col=0, parse_dates=True)
    if frame.empty:
        raise SystemExit("primary daily series is empty")
    values = pd.to_numeric(frame.iloc[:, 0], errors="coerce")
    values.index = pd.to_datetime(values.index).normalize()
    later = values[values.index >= PERIOD_START]
    if later.isna().any():
        raise SystemExit("primary daily series contains non-numeric rows")
    if later.empty:
        raise SystemExit("primary daily series has no 2024+ observations")

    result = {
        "analysis": "X02_EXECUTION_STABILITY_V1",
        "primary_spec": "original_gate_CONSERVATIVE",
        "period": "later",
        "period_start": str(PERIOD_START.date()),
        "rolling_windows_trading_days": list(ROLLING_WINDOWS),
        "descriptive_only": True,
        "parameter_search": False,
        "live_trading_authorized": False,
        "lineage": lineage,
        "statistics": analyze_stability(later),
        "interpretation_boundary": (
            "Calendar-year and fixed-window dispersion describe historical regime concentration in the frozen execution path only; "
            "they do not create pristine OOS evidence or authorize retuning."
        ),
    }
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(render_markdown(result), encoding="utf-8")
    print(render_markdown(result))


if __name__ == "__main__":
    main()
