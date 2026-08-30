"""Strict OOS experiment using point-in-time valuation, size and industry data."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from auto_factor_backtest import (
    _fit_model,
    _portfolio_row,
    load_or_build_panel,
    matured_train_dates,
)
from auxiliary_data_loader import load_auxiliary_panel, load_industry_panel
from config import OUTPUT_DIR
from factor_factory import (
    BASE_FEATURES,
    BalancedGenerator,
    FactorExpression,
    FactorRegistry,
    apply_oos_evidence,
    evaluate_candidates,
    rank_factor_matrix,
    select_diverse_factors,
)
from factor_transfer_backtest import _json_safe, calendar
from multi_expert_oos_backtest import prepare_snapshot, signal_dates, subperiod_summary, summarize


ENRICHED_FEATURES = (
    "log_float_market_cap",
    "turnover_rate_pct",
    "earnings_yield",
    "book_to_price",
    "sales_to_price",
    "cashflow_yield",
)
ALL_CANDIDATE_BASES = BASE_FEATURES + ENRICHED_FEATURES


@dataclass(frozen=True)
class Config:
    market: str = "csi800"
    start: str = "2015-01-05"
    end: str = "2026-05-29"
    holding_days: int = 21
    train_periods: int = 36
    min_train_periods: int = 30
    top_n: int = 100
    liquidity_quantile: float = 0.20
    min_price: float = 2.0
    open_cost: float = 0.0003
    close_cost: float = 0.0013
    seed: int = 20260718
    bootstrap_samples: int = 2000
    candidate_limit: int = 160
    factor_count: int = 10
    max_factor_correlation: float = 0.70
    min_abs_ic: float = 0.005


def _safe_inverse(values: pd.Series, positive_only: bool = False) -> pd.Series:
    valid = values.where(values > 0.05) if positive_only else values.where(values.abs() > 0.05)
    return (1.0 / valid).clip(-5.0, 5.0)


def enrich_panel(panel: pd.DataFrame, cache_path: Path | None = None) -> pd.DataFrame:
    if cache_path is not None and cache_path.exists():
        return pd.read_pickle(cache_path)
    auxiliary = load_auxiliary_panel(panel.index)
    industries = load_industry_panel(panel.index)
    result = panel.join(auxiliary).join(industries)
    result["log_float_market_cap"] = np.log(result["float_market_cap_est"].where(result["float_market_cap_est"] > 0))
    result["earnings_yield"] = _safe_inverse(result["pe_ttm"], positive_only=True)
    result["book_to_price"] = _safe_inverse(result["pb_mrq"], positive_only=True)
    result["sales_to_price"] = _safe_inverse(result["ps_ttm"], positive_only=True)
    result["cashflow_yield"] = _safe_inverse(result["pcf_ncf_ttm"], positive_only=False)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(".tmp")
        result.to_pickle(temporary)
        temporary.replace(cache_path)
    return result


def prepare_enriched_snapshot(snapshot: pd.DataFrame, config: Config, require_label: bool) -> pd.DataFrame:
    frame = prepare_snapshot(snapshot, config, require_label=require_label)
    if frame.empty:
        return frame
    # Missing provider status is excluded conservatively.  The entry-day Qlib
    # tradability check remains in prepare_snapshot as a second line of defence.
    return frame.loc[frame["trade_status"].eq(1) & frame["is_st"].eq(0)].copy()


def prepare_train(panel: pd.DataFrame, dates: list[pd.Timestamp], config: Config) -> pd.DataFrame:
    parts = []
    for date in dates:
        part = prepare_enriched_snapshot(panel.xs(date, level="datetime"), config, require_label=True)
        if part.empty:
            continue
        part["datetime"] = date
        parts.append(part.set_index("datetime", append=True).reorder_levels(["datetime", "instrument"]))
    return pd.concat(parts).sort_index() if parts else pd.DataFrame()


def style_neutralize_score(score: pd.Series, frame: pd.DataFrame, ridge: float = 1e-4) -> pd.Series:
    """Remove same-date industry, size and volatility exposures from a score."""

    controls = pd.DataFrame(index=score.index)
    controls["score"] = score
    controls["size"] = frame["log_float_market_cap"].rank(pct=True) - 0.5
    controls["volatility"] = frame["vol_60"].rank(pct=True) - 0.5
    controls["industry"] = frame["industry_code"].astype("string")
    valid = controls.dropna()
    output = pd.Series(np.nan, index=score.index, dtype=float, name="neutral_score")
    if len(valid) < 50 or valid["industry"].nunique() < 2:
        return score.rank(pct=True).rename("neutral_score")
    dummies = pd.get_dummies(valid["industry"], prefix="industry", drop_first=True, dtype=float)
    design = pd.concat([valid[["size", "volatility"]], dummies], axis=1)
    x = np.column_stack([np.ones(len(design)), design.to_numpy(dtype=float)])
    # Neutralise the ordering that actually drives portfolio selection, not
    # arbitrary raw model-score units.
    y = valid["score"].rank(pct=True).to_numpy(dtype=float)
    penalty = np.eye(x.shape[1]) * ridge
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(x.T @ x + penalty, x.T @ y)
    residual = y - x @ beta
    # Ranking residuals for portfolio selection can reintroduce a small rank
    # exposure.  One second projection removes that effect deterministically.
    ranked_residual = pd.Series(residual).rank(pct=True).to_numpy(dtype=float)
    beta = np.linalg.solve(x.T @ x + penalty, x.T @ ranked_residual)
    output.loc[valid.index] = ranked_residual - x @ beta
    return output


def _model_scores(
    ranked_train: pd.DataFrame,
    current: pd.DataFrame,
    expressions: dict[str, FactorExpression],
    metrics: pd.DataFrame,
    selected: list[str],
    target: pd.Series,
    seed: int,
) -> tuple[pd.Series, pd.DataFrame]:
    orientations = metrics.set_index("name")["orientation"].astype(float)
    current_ranked = rank_factor_matrix(current, [expressions[name] for name in selected])
    train_x = ranked_train[selected].mul(orientations[selected], axis=1)
    current_x = current_ranked[selected].mul(orientations[selected], axis=1)
    columns = [f"factor_{number:03d}" for number in range(len(selected))]
    train_x.columns = columns
    current_x.columns = columns
    model = _fit_model(train_x, target, seed)
    return pd.Series(model.predict(current_x), index=current.index), current_ranked


def run_oos(panel: pd.DataFrame, dates: list[pd.Timestamp], config: Config):
    expressions_list = BalancedGenerator().generate(ALL_CANDIDATE_BASES, config.candidate_limit)
    expressions = {expression.name: expression for expression in expressions_list}
    base_expressions = [FactorExpression("base", name) for name in BASE_FEATURES]
    registry = FactorRegistry()
    strategies = (
        "base_lgb",
        "enriched_train_lgb",
        "enriched_train_neutral",
        "enriched_oos_lgb",
        "enriched_oos_neutral",
        "eligible_equal_weight",
    )
    previous = {strategy: set() for strategy in strategies}
    pending_factor_scores: dict[int, dict[str, pd.Series]] = {}
    period_rows = []
    selection_rows = []

    for period, date in enumerate(dates):
        matured = pending_factor_scores.pop(period - 2, None)
        if matured is not None:
            matured_date = dates[period - 2]
            realized = panel.xs(matured_date, level="datetime")["forward_21"]
            for name, score in matured.items():
                pair = pd.concat([score.rename("score"), realized.rename("return")], axis=1).dropna()
                if len(pair) >= 20:
                    registry.record_oos(name, pair["score"].corr(pair["return"], method="spearman"), matured_date)

        train_dates = matured_train_dates(dates, period, config.train_periods)
        if len(train_dates) < config.min_train_periods:
            continue
        train = prepare_train(panel, train_dates, config)
        current = prepare_enriched_snapshot(panel.xs(date, level="datetime"), config, require_label=False)
        if train.empty or len(current) < config.top_n:
            continue
        ranked_train = rank_factor_matrix(train, expressions_list)
        raw_metrics = evaluate_candidates(ranked_train, train["forward_21"], expressions_list)
        oos_metrics = apply_oos_evidence(raw_metrics, registry)
        train_selected = select_diverse_factors(
            raw_metrics, ranked_train, config.factor_count, config.max_factor_correlation, config.min_abs_ic,
            expressions=expressions, max_per_family=4,
        )
        oos_selected = select_diverse_factors(
            oos_metrics, ranked_train, config.factor_count, config.max_factor_correlation, config.min_abs_ic,
            expressions=expressions, max_per_family=4,
        )
        if not train_selected or not oos_selected:
            continue
        registry.update(oos_metrics, oos_selected, date)
        target = train["forward_21"].groupby(level="datetime").rank(pct=True) - 0.5

        base_train = ranked_train[list(BASE_FEATURES)].copy()
        base_current = rank_factor_matrix(current, base_expressions)
        base_model = _fit_model(base_train, target, config.seed + period * 10)
        base_score = pd.Series(base_model.predict(base_current), index=current.index)
        train_score, _ = _model_scores(
            ranked_train, current, expressions, raw_metrics, train_selected, target, config.seed + period * 10 + 1
        )
        train_neutral_score = style_neutralize_score(train_score, current)
        oos_score, oos_current_ranked = _model_scores(
            ranked_train, current, expressions, oos_metrics, oos_selected, target, config.seed + period * 10 + 2
        )
        neutral_score = style_neutralize_score(oos_score, current)
        orientations = oos_metrics.set_index("name")["orientation"]
        pending_factor_scores[period] = {
            name: (oos_current_ranked[name] * float(orientations[name])).rename(name) for name in oos_selected
        }
        scores = {
            "base_lgb": base_score,
            "enriched_train_lgb": train_score,
            "enriched_train_neutral": train_neutral_score,
            "enriched_oos_lgb": oos_score,
            "enriched_oos_neutral": neutral_score,
        }
        portfolios = {name: value.nlargest(config.top_n).index.tolist() for name, value in scores.items()}
        portfolios["eligible_equal_weight"] = current.index.tolist()
        oos_holdings = set(portfolios["enriched_oos_lgb"])
        for strategy, instruments in portfolios.items():
            row, previous[strategy] = _portfolio_row(
                strategy, instruments, current, previous[strategy], date, period, config
            )
            row["holdings"] = "|".join(instruments)
            row["oos_portfolio_overlap"] = (
                len(oos_holdings.intersection(instruments)) / max(config.top_n, 1)
                if strategy != "eligible_equal_weight"
                else np.nan
            )
            period_rows.append(row)
        metric_map = oos_metrics.set_index("name")
        for rank, name in enumerate(oos_selected, 1):
            metric = metric_map.loc[name]
            selection_rows.append(
                {
                    "signal_date": date,
                    "rank": rank,
                    "factor": name,
                    "mean_training_ic": metric["mean_ic"],
                    "mean_matured_oos_ic": metric["mean_oos_ic"],
                    "oos_observations": int(metric["oos_observations"]),
                    "oos_multiplier": metric["oos_multiplier"],
                    "score": metric["score"],
                }
            )
        print(
            f"  OOS {date.date()} enriched={train_selected[0]} oos={oos_selected[0]} "
            f"known_oos={int((oos_metrics['oos_observations'] >= 4).sum())}",
            flush=True,
        )
    periods = pd.DataFrame(period_rows)
    if periods.empty:
        raise ValueError("No enriched OOS periods were produced")
    return periods.sort_values(["signal_date", "strategy"]).reset_index(drop=True), pd.DataFrame(selection_rows), registry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enriched automatic factor strict OOS backtest")
    parser.add_argument("--start", default=Config.start)
    parser.add_argument("--end", default=Config.end)
    parser.add_argument("--train-periods", type=int, default=Config.train_periods)
    parser.add_argument("--min-train-periods", type=int, default=Config.min_train_periods)
    parser.add_argument("--top-n", type=int, default=Config.top_n)
    parser.add_argument("--candidate-limit", type=int, default=Config.candidate_limit)
    parser.add_argument("--factor-count", type=int, default=Config.factor_count)
    parser.add_argument("--bootstrap-samples", type=int, default=Config.bootstrap_samples)
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    config = Config(
        start=args.start,
        end=args.end,
        train_periods=args.train_periods,
        min_train_periods=args.min_train_periods,
        top_n=args.top_n,
        candidate_limit=args.candidate_limit,
        factor_count=args.factor_count,
        bootstrap_samples=args.bootstrap_samples,
    )
    dates = signal_dates(calendar(), config)
    base_panel = load_or_build_panel(config, dates)
    enriched_cache = OUTPUT_DIR / "cache" / (
        f"enriched_monthly_panel_{dates[0]:%Y%m%d}_{dates[-1]:%Y%m%d}_{len(dates)}.pkl"
    )
    panel = enrich_panel(base_panel, enriched_cache)
    periods, selections, registry = run_oos(panel, dates, config)
    normal = summarize(periods, config, cost_multiplier=1.0)
    double = summarize(periods, config, cost_multiplier=2.0)
    subperiods = subperiod_summary(periods, config)
    frequency = selections.groupby("factor", as_index=False).agg(
        selected_periods=("signal_date", "size"),
        mean_training_ic=("mean_training_ic", "mean"),
        mean_matured_oos_ic=("mean_matured_oos_ic", "mean"),
    ).sort_values("selected_periods", ascending=False)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_DIR / "enriched_factor" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    periods.to_csv(out_dir / "oos_periods.csv", index=False, encoding="utf-8-sig")
    selections.to_csv(out_dir / "factor_selections.csv", index=False, encoding="utf-8-sig")
    frequency.to_csv(out_dir / "factor_frequency.csv", index=False, encoding="utf-8-sig")
    normal.to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig")
    double.to_csv(out_dir / "summary_double_cost.csv", index=False, encoding="utf-8-sig")
    subperiods.to_csv(out_dir / "subperiods.csv", index=False, encoding="utf-8-sig")
    (out_dir / "factor_registry.json").write_text(
        json.dumps(_json_safe(registry.snapshot()), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    payload = _json_safe(
        {
            "run": stamp,
            "config": asdict(config),
            "features": {"price_volume": list(BASE_FEATURES), "point_in_time_auxiliary": list(ENRICHED_FEATURES)},
            "generator": "balanced operator sampling with max four exposures per factor family",
            "summary": normal.to_dict("records"),
            "summary_double_cost": double.to_dict("records"),
            "subperiods": subperiods.to_dict("records"),
            "output_dir": str(out_dir),
        }
    )
    (out_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "enriched_factor_latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(normal.to_string(index=False), flush=True)
    print(f"Result: {out_dir / 'result.json'}", flush=True)
    return payload


if __name__ == "__main__":
    main()
