"""Lagged, auditable drawdown controls for the enriched factor portfolio.

The module consumes a completed OOS holdings file.  It never changes the
stock-selection model and every exposure decision for period T is computed
from returns that matured before T.  Cash is assumed to earn zero.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from auto_factor_backtest import Config
from config import OUTPUT_DIR
from factor_transfer_backtest import _json_safe
from multi_expert_oos_backtest import subperiod_summary, summarize


@dataclass(frozen=True)
class PortfolioSpec:
    name: str
    sleeves: tuple[tuple[str, float], ...]
    target_volatility: float | None = None
    trend_lookback: int | None = None
    defensive_exposure: float = 0.35
    minimum_vol_history: int = 6
    volatility_lookback: int = 12
    maximum_exposure: float = 1.0


SPECS = (
    PortfolioSpec("champion_full", (("enriched_train_lgb", 1.0),)),
    PortfolioSpec("blend75_full", (("enriched_train_lgb", 0.75), ("enriched_train_neutral", 0.25))),
    PortfolioSpec("blend50_full", (("enriched_train_lgb", 0.50), ("enriched_train_neutral", 0.50))),
    PortfolioSpec("champion_vol12", (("enriched_train_lgb", 1.0),), target_volatility=0.12),
    PortfolioSpec("blend75_vol12", (("enriched_train_lgb", 0.75), ("enriched_train_neutral", 0.25)), target_volatility=0.12),
    PortfolioSpec("blend75_vol10", (("enriched_train_lgb", 0.75), ("enriched_train_neutral", 0.25)), target_volatility=0.10),
    PortfolioSpec(
        "blend75_vol12_trend6",
        (("enriched_train_lgb", 0.75), ("enriched_train_neutral", 0.25)),
        target_volatility=0.12,
        trend_lookback=6,
    ),
    PortfolioSpec(
        "blend75_vol10_trend6",
        (("enriched_train_lgb", 0.75), ("enriched_train_neutral", 0.25)),
        target_volatility=0.10,
        trend_lookback=6,
    ),
    PortfolioSpec(
        "blend75_vol8_trend6",
        (("enriched_train_lgb", 0.75), ("enriched_train_neutral", 0.25)),
        target_volatility=0.08,
        trend_lookback=6,
        defensive_exposure=0.10,
        maximum_exposure=0.80,
    ),
    PortfolioSpec(
        "champion_vol8_trend6",
        (("enriched_train_lgb", 1.0),),
        target_volatility=0.08,
        trend_lookback=6,
        defensive_exposure=0.10,
        maximum_exposure=0.80,
    ),
    PortfolioSpec(
        "champion_vol6_trend6",
        (("enriched_train_lgb", 1.0),),
        target_volatility=0.06,
        trend_lookback=6,
        defensive_exposure=0.0,
        maximum_exposure=0.70,
    ),
)


def _holdings(value: object) -> list[str]:
    if not isinstance(value, str) or not value:
        return []
    return [item for item in value.split("|") if item]


def _target_weights(rows: dict[str, pd.Series], spec: PortfolioSpec, exposure: float) -> dict[str, float]:
    weights: dict[str, float] = {}
    for strategy, sleeve_weight in spec.sleeves:
        names = _holdings(rows[strategy]["holdings"])
        if not names:
            continue
        stock_weight = exposure * sleeve_weight / len(names)
        for name in names:
            weights[name] = weights.get(name, 0.0) + stock_weight
    return weights


def lagged_exposure(
    spec: PortfolioSpec,
    prior_returns: list[float],
    prior_benchmark_returns: list[float],
    periods_per_year: float,
) -> tuple[float, float, float]:
    """Return exposure, ex-ante annualised volatility and lagged trend."""
    exposure = spec.maximum_exposure
    estimated_volatility = np.nan
    trend = np.nan
    if spec.target_volatility is not None and len(prior_returns) >= spec.minimum_vol_history:
        history = np.asarray(prior_returns[-spec.volatility_lookback :], dtype=float)
        estimated_volatility = float(np.std(history, ddof=1) * np.sqrt(periods_per_year))
        if np.isfinite(estimated_volatility) and estimated_volatility > 0:
            exposure = min(exposure, float(np.clip(spec.target_volatility / estimated_volatility, 0.20, 1.0)))
    if spec.trend_lookback is not None and len(prior_benchmark_returns) >= spec.trend_lookback:
        recent = prior_benchmark_returns[-spec.trend_lookback :]
        trend = float(np.prod(1.0 + np.asarray(recent, dtype=float)) - 1.0)
        if trend <= 0:
            exposure = min(exposure, spec.defensive_exposure)
    return exposure, estimated_volatility, trend


def simulate(source: pd.DataFrame, config: Config, specs: tuple[PortfolioSpec, ...] = SPECS) -> pd.DataFrame:
    frame = source.copy()
    frame["signal_date"] = pd.to_datetime(frame["signal_date"])
    by_date = {date: part.set_index("strategy") for date, part in frame.groupby("signal_date", sort=True)}
    dates = sorted(by_date)
    benchmark_history: list[float] = []
    return_history = {spec.name: [] for spec in specs}
    previous_weights = {spec.name: {} for spec in specs}
    previous_benchmark_weights = {spec.name: {} for spec in specs}
    rows: list[dict] = []
    periods_per_year = 252 / config.holding_days

    for date in dates:
        indexed = by_date[date]
        benchmark = indexed.loc["eligible_equal_weight"]
        for spec in specs:
            sleeve_rows = {name: indexed.loc[name] for name, _ in spec.sleeves}
            exposure, estimated_volatility, trend = lagged_exposure(
                spec, return_history[spec.name], benchmark_history, periods_per_year
            )
            target = _target_weights(sleeve_rows, spec, exposure)
            previous = previous_weights[spec.name]
            instruments = set(target) | set(previous)
            buy_turnover = float(sum(max(target.get(name, 0.0) - previous.get(name, 0.0), 0.0) for name in instruments))
            sell_turnover = float(sum(max(previous.get(name, 0.0) - target.get(name, 0.0), 0.0) for name in instruments))
            cost = buy_turnover * config.open_cost + sell_turnover * config.close_cost
            stock_gross = float(sum(weight * float(sleeve_rows[name]["gross_return"]) for name, weight in spec.sleeves))
            gross = exposure * stock_gross
            net = (1.0 + gross) * (1.0 - cost) - 1.0
            benchmark_names = _holdings(benchmark.get("holdings"))
            benchmark_target = {
                name: exposure / len(benchmark_names) for name in benchmark_names
            } if benchmark_names else {}
            benchmark_previous = previous_benchmark_weights[spec.name]
            benchmark_instruments = set(benchmark_target) | set(benchmark_previous)
            benchmark_buys = sum(
                max(benchmark_target.get(name, 0.0) - benchmark_previous.get(name, 0.0), 0.0)
                for name in benchmark_instruments
            )
            benchmark_sells = sum(
                max(benchmark_previous.get(name, 0.0) - benchmark_target.get(name, 0.0), 0.0)
                for name in benchmark_instruments
            )
            benchmark_cost = benchmark_buys * config.open_cost + benchmark_sells * config.close_cost
            benchmark_gross = exposure * float(benchmark["gross_return"])
            risk_matched_benchmark_return = (1.0 + benchmark_gross) * (1.0 - benchmark_cost) - 1.0
            missing = int(sum(round(weight * float(sleeve_rows[name]["missing_returns"])) for name, weight in spec.sleeves))
            rows.append(
                {
                    "signal_date": date,
                    "period": int(benchmark["period"]),
                    "strategy": spec.name,
                    "n_holdings": len(target),
                    "universe_size": int(benchmark["universe_size"]),
                    "gross_return": gross,
                    "cost": cost,
                    "net_return": net,
                    "buy_turnover": buy_turnover,
                    "sell_turnover": sell_turnover,
                    "missing_returns": missing,
                    "exposure": exposure,
                    "estimated_volatility": estimated_volatility,
                    "lagged_benchmark_trend": trend,
                    "risk_matched_benchmark_return": risk_matched_benchmark_return,
                    "risk_matched_benchmark_cost": benchmark_cost,
                }
            )
            return_history[spec.name].append(net)
            previous_weights[spec.name] = target
            previous_benchmark_weights[spec.name] = benchmark_target
        rows.append({**benchmark.to_dict(), "signal_date": date, "strategy": "eligible_equal_weight", "exposure": 1.0})
        benchmark_history.append(float(benchmark["net_return"]))
    return pd.DataFrame(rows).sort_values(["signal_date", "strategy"]).reset_index(drop=True)


def _add_risk_metrics(
    summary: pd.DataFrame, periods: pd.DataFrame, cost_multiplier: float = 1.0
) -> pd.DataFrame:
    result = summary.copy()
    exposure = periods.groupby("strategy")["exposure"].agg(["mean", "min"])
    result["mean_exposure"] = result["strategy"].map(exposure["mean"])
    result["minimum_exposure"] = result["strategy"].map(exposure["min"])
    result["return_over_drawdown"] = result["annual_return_net"] / result["endpoint_max_drawdown"].abs()
    periods_per_year = 12.0
    annual_risk_excess: dict[str, float] = {}
    risk_ir: dict[str, float] = {}
    for strategy, part in periods.dropna(subset=["risk_matched_benchmark_return"]).groupby("strategy"):
        strategy_return = (1.0 + part["net_return"].to_numpy()) * (
            1.0 - part["cost"].to_numpy() * (cost_multiplier - 1.0)
        ) - 1.0
        benchmark_return = (1.0 + part["risk_matched_benchmark_return"].to_numpy()) * (
            1.0 - part["risk_matched_benchmark_cost"].to_numpy() * (cost_multiplier - 1.0)
        ) - 1.0
        excess = strategy_return - benchmark_return
        annual_risk_excess[strategy] = float((1.0 + excess).prod() ** (periods_per_year / len(excess)) - 1.0)
        tracking_error = float(np.std(excess, ddof=1) * np.sqrt(periods_per_year))
        risk_ir[strategy] = annual_risk_excess[strategy] / tracking_error if tracking_error > 0 else np.nan
    result["annual_risk_matched_excess"] = result["strategy"].map(annual_risk_excess)
    result["risk_matched_information_ratio"] = result["strategy"].map(risk_ir)
    return result


def main() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=OUTPUT_DIR / "enriched_factor" / "20260718_073734" / "oos_periods.csv")
    args = parser.parse_args()
    config = Config(seed=20260718)
    source = pd.read_csv(args.source)
    periods = simulate(source, config)
    normal = _add_risk_metrics(summarize(periods, config), periods)
    double = _add_risk_metrics(summarize(periods, config, cost_multiplier=2.0), periods, cost_multiplier=2.0)
    subperiods = subperiod_summary(periods, config)
    run = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = OUTPUT_DIR / "drawdown_control" / run
    output.mkdir(parents=True, exist_ok=False)
    periods.to_csv(output / "oos_periods.csv", index=False, encoding="utf-8-sig")
    normal.to_csv(output / "summary.csv", index=False, encoding="utf-8-sig")
    double.to_csv(output / "summary_double_cost.csv", index=False, encoding="utf-8-sig")
    subperiods.to_csv(output / "subperiods.csv", index=False, encoding="utf-8-sig")
    payload = {
        "run": run,
        "source": str(args.source),
        "method": "all exposure decisions use only lagged realised OOS returns",
        "specifications": [spec.__dict__ for spec in SPECS],
        "summary": normal.to_dict("records"),
        "summary_double_cost": double.to_dict("records"),
    }
    (output / "result.json").write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    print(normal.to_string(index=False))
    print(f"Saved: {output}")
    return payload


if __name__ == "__main__":
    main()
