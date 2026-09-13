"""Preregistered V5 all-weather baseline: frozen X02 in RISK_ON, cash otherwise.

This module intentionally does not modify X02.  It consumes the exact
`original_gate_CONSERVATIVE` next-record daily return series produced by the
X02 execution-validation chain and applies a causal T-1-close market-regime
router fixed in V5_ALL_WEATHER_PREREGISTRATION.md before the first V5 result.

All historical results are development evidence.  2024+ has already been
inspected during X02 work and is not pristine OOS.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as engine
import v4_survivor_wrapper as survivor
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
X02_OUT = ROOT / "output" / "x02_reproduction_20260912"
X02_DAILY = X02_OUT / "original_gate_CONSERVATIVE_next_bar_daily.csv"
OUT = ROOT / "output" / "v5_all_weather_baseline"
REPORT = OUT / "report.json"
ROUTES = OUT / "regime_routes.csv"
PREREG = ROOT / "V5_ALL_WEATHER_PREREGISTRATION.md"

REGIME_RISK_ON = "RISK_ON"
REGIME_NEUTRAL = "NEUTRAL"
REGIME_RISK_OFF = "RISK_OFF"

CONTRACT = {
    "version": "V5_ALL_WEATHER_REGIME_BASELINE_V1",
    "x02_sleeve": "original_gate_CONSERVATIVE next-record daily returns",
    "signal_timing": "market state after T-1 close controls allocation on T",
    "breadth20": "20-trading-day rolling mean of breadth; min_periods=15",
    "risk_on": "not weak_market AND breadth5>0 AND breadth20>0 AND money_effect>0",
    "risk_off": "weak_market OR breadth20<=0",
    "neutral": "all other fully observed states; missing inputs also neutral",
    "allocation": {REGIME_RISK_ON: 1.0, REGIME_NEUTRAL: 0.0, REGIME_RISK_OFF: 0.0},
    "parameter_search": False,
    "x02_retuning": False,
    "live_trading_authorized": False,
}

PERIODS = {
    "all": (None, None),
    "development_2021_2023": (None, pd.Timestamp("2023-12-31")),
    "historical_later_2024_plus": (pd.Timestamp("2024-01-01"), None),
}


def _finite_series(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise RuntimeError("return series contains missing or non-finite values")
    if (values <= -1.0).any():
        raise RuntimeError("return series contains value <= -100%")
    return values.astype(float)


def load_x02_daily(path: Path = X02_DAILY) -> pd.Series:
    if not path.exists():
        raise FileNotFoundError(
            f"missing frozen X02 next-record daily series: {path}; run run_x02_execution_validation.py first"
        )
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    if frame.shape[1] != 1:
        raise RuntimeError(f"expected one X02 daily return column, found {list(frame.columns)}")
    series = _finite_series(frame.iloc[:, 0])
    index = pd.DatetimeIndex(pd.to_datetime(series.index)).normalize()
    if index.duplicated().any():
        raise RuntimeError("X02 daily series contains duplicate dates")
    series.index = index
    series = series.sort_index()
    series.name = "x02_return"
    return series


def _assert_daily_market_consistency(frame: pd.DataFrame, columns: list[str]) -> None:
    grouped = frame.groupby("date", sort=False)[columns]
    inconsistent = grouped.nunique(dropna=False).gt(1).any(axis=1)
    if bool(inconsistent.any()):
        offenders = [str(pd.Timestamp(x).date()) for x in inconsistent.index[inconsistent][:10]]
        raise RuntimeError(f"market-state fields vary within the same date: {offenders}")


def build_regime_table(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["date", "breadth", "breadth5", "money_effect", "weak_market"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"market frame missing required regime fields: {missing}")

    x = frame[required].copy()
    x["date"] = pd.to_datetime(x["date"]).dt.normalize()
    _assert_daily_market_consistency(x, required[1:])
    daily = x.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    daily = daily.rename(columns={"date": "signal_date"})
    for column in ("breadth", "breadth5", "money_effect"):
        daily[column] = pd.to_numeric(daily[column], errors="coerce")
    daily["breadth20"] = daily["breadth"].rolling(20, min_periods=15).mean()

    observed = daily[["breadth5", "breadth20", "money_effect", "weak_market"]].notna().all(axis=1)
    weak = daily["weak_market"].fillna(False).astype(bool)
    risk_off = observed & (weak | daily["breadth20"].le(0))
    risk_on = (
        observed
        & ~risk_off
        & ~weak
        & daily["breadth5"].gt(0)
        & daily["breadth20"].gt(0)
        & daily["money_effect"].gt(0)
    )

    daily["regime"] = REGIME_NEUTRAL
    daily.loc[risk_off, "regime"] = REGIME_RISK_OFF
    daily.loc[risk_on, "regime"] = REGIME_RISK_ON
    daily["regime_inputs_observed"] = observed

    # State after signal_date close is the only state allowed to control the next
    # trading session.  This explicit shift is the anti-leakage boundary.
    daily["trade_date"] = daily["signal_date"].shift(-1)
    daily = daily.dropna(subset=["trade_date"]).copy()
    daily["trade_date"] = pd.to_datetime(daily["trade_date"]).dt.normalize()
    return daily[
        [
            "signal_date", "trade_date", "breadth", "breadth5", "breadth20",
            "money_effect", "weak_market", "regime_inputs_observed", "regime",
        ]
    ].reset_index(drop=True)


def route_x02(x02: pd.Series, regimes: pd.DataFrame) -> pd.DataFrame:
    x02 = _finite_series(x02.copy())
    x02.index = pd.DatetimeIndex(pd.to_datetime(x02.index)).normalize()
    if regimes["trade_date"].duplicated().any():
        raise RuntimeError("regime table contains duplicate trade_date rows")
    route = regimes.set_index("trade_date").reindex(x02.index)
    missing_state = route["regime"].isna()
    route.loc[missing_state, "regime"] = REGIME_NEUTRAL
    route.loc[missing_state, "regime_inputs_observed"] = False
    allocation = route["regime"].eq(REGIME_RISK_ON).astype(float)
    result = route.copy()
    result["x02_return"] = x02.to_numpy(dtype=float)
    result["allocation"] = allocation.to_numpy(dtype=float)
    result["routed_return"] = result["x02_return"] * result["allocation"]
    result["missing_route_state"] = missing_state.to_numpy(dtype=bool)
    result.index.name = "trade_date"
    return result


def metrics(series: pd.Series) -> dict[str, Any]:
    s = _finite_series(series.copy()).sort_index()
    if s.empty:
        return {"n_days": 0}
    wealth = np.concatenate([[1.0], np.cumprod(1.0 + s.to_numpy(dtype=float))])
    peaks = np.maximum.accumulate(wealth)
    drawdowns = wealth / peaks - 1.0
    total_return = float(wealth[-1] - 1.0)
    elapsed_days = max(1, int((s.index[-1] - s.index[0]).days))
    cagr = float(wealth[-1] ** (365.25 / elapsed_days) - 1.0)
    vol = float(s.std(ddof=1)) if len(s) > 1 else 0.0
    sharpe = float(s.mean() / vol * math.sqrt(252.0)) if vol > 0 else None
    active = s[s.ne(0)]
    yearly = (1.0 + s).groupby(s.index.year).prod() - 1.0
    max_drawdown = float(drawdowns.min())
    return {
        "n_days": int(len(s)),
        "active_days": int(len(active)),
        "active_fraction": float(len(active) / len(s)),
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown_corrected": max_drawdown,
        "sharpe": sharpe,
        "calmar": float(cagr / abs(max_drawdown)) if max_drawdown < 0 else None,
        "mean_active_day": float(active.mean()) if len(active) else None,
        "active_win_rate": float((active > 0).mean()) if len(active) else None,
        "worst_day": float(s.min()),
        "best_day": float(s.max()),
        "yearly_returns": {str(int(year)): float(value) for year, value in yearly.items()},
    }


def _slice(series: pd.Series, start: pd.Timestamp | None, end: pd.Timestamp | None) -> pd.Series:
    result = series
    if start is not None:
        result = result[result.index >= start]
    if end is not None:
        result = result[result.index <= end]
    return result


def _regime_diagnostics(routes: pd.DataFrame) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    for regime in (REGIME_RISK_ON, REGIME_NEUTRAL, REGIME_RISK_OFF):
        subset = routes[routes["regime"].eq(regime)]
        active = subset.loc[subset["x02_return"].ne(0), "x02_return"]
        diagnostics[regime] = {
            "trade_days": int(len(subset)),
            "fraction_of_days": float(len(subset) / len(routes)) if len(routes) else None,
            "x02_active_days": int(len(active)),
            "x02_active_mean_return": float(active.mean()) if len(active) else None,
            "x02_active_win_rate": float((active > 0).mean()) if len(active) else None,
            "x02_compounded_return_on_regime_dates": (
                float((1.0 + subset["x02_return"]).prod() - 1.0) if len(subset) else None
            ),
        }
    transitions = routes["regime"].ne(routes["regime"].shift(1))
    return {
        "by_regime": diagnostics,
        "regime_transitions": int(max(0, transitions.sum() - 1)),
        "missing_route_state_days": int(routes["missing_route_state"].sum()),
        "risk_on_allocation_days": int(routes["allocation"].eq(1.0).sum()),
    }


def prepare_market_frame() -> pd.DataFrame:
    # Reuse the same daily preparation stack that feeds X02.  No V5-specific
    # market feature is fitted other than the preregistered breadth20 rolling mean.
    config = engine.base.Config(start="2015-01-01", end="2026-09-03")
    return survivor.prepare(config)


def run() -> dict[str, Any]:
    if not PREREG.exists():
        raise FileNotFoundError(PREREG)
    x02 = load_x02_daily()
    market_frame = prepare_market_frame()
    regimes = build_regime_table(market_frame)
    routes = route_x02(x02, regimes)

    x02_series = routes["x02_return"].copy()
    x02_series.index = pd.DatetimeIndex(routes.index)
    routed_series = routes["routed_return"].copy()
    routed_series.index = pd.DatetimeIndex(routes.index)

    periods: dict[str, Any] = {}
    for name, (start, end) in PERIODS.items():
        frozen = metrics(_slice(x02_series, start, end))
        routed = metrics(_slice(routed_series, start, end))
        periods[name] = {
            "frozen_x02": frozen,
            "v5_routed": routed,
            "delta": {
                "cagr": routed.get("cagr", 0.0) - frozen.get("cagr", 0.0),
                "total_return": routed.get("total_return", 0.0) - frozen.get("total_return", 0.0),
                "max_drawdown_corrected": routed.get("max_drawdown_corrected", 0.0) - frozen.get("max_drawdown_corrected", 0.0),
                "sharpe": (
                    routed["sharpe"] - frozen["sharpe"]
                    if routed.get("sharpe") is not None and frozen.get("sharpe") is not None
                    else None
                ),
            },
        }

    OUT.mkdir(parents=True, exist_ok=True)
    routes.reset_index().to_csv(ROUTES, index=False)
    report = {
        "contract": CONTRACT,
        "preregistration_sha256": sha256_file(PREREG),
        "inputs": {
            "x02_daily_file": str(X02_DAILY.relative_to(ROOT)),
            "x02_daily_sha256": sha256_file(X02_DAILY),
            "x02_first_date": str(x02.index.min().date()),
            "x02_last_date": str(x02.index.max().date()),
            "x02_days": int(len(x02)),
        },
        "anti_leakage": {
            "regime_source": "existing point-in-time daily market-state construction",
            "routing": "signal_date T-1 state is shifted to trade_date T",
            "same_day_T_market_data_used_for_route": False,
            "future_returns_used_for_route": False,
        },
        "periods": periods,
        "regime_diagnostics": _regime_diagnostics(routes),
        "interpretation_boundary": (
            "This first V5 result is development evidence only. It tests a frozen X02/cash router, "
            "does not complete an all-weather portfolio, does not authorize threshold retuning, and does not authorize live trading."
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str), flush=True)
    return report


if __name__ == "__main__":
    run()
