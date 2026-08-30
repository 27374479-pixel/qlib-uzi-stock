"""Strict walk-forward backtest for an automatically refreshed factor factory."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from config import OUTPUT_DIR
from factor_factory import (
    BASE_FEATURES,
    DeterministicGenerator,
    FactorExpression,
    FactorRegistry,
    evaluate_candidates,
    rank_factor_matrix,
    select_diverse_factors,
)
from factor_transfer_backtest import _json_safe, calendar
from multi_expert_oos_backtest import load_panel, prepare_snapshot, signal_dates, subperiod_summary, summarize


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
    seed: int = 20260717
    bootstrap_samples: int = 2000
    candidate_limit: int = 120
    factor_count: int = 12
    max_factor_correlation: float = 0.70
    min_abs_ic: float = 0.005


def _cache_paths(config: Config, dates: list[pd.Timestamp]) -> tuple[Path, Path]:
    identity = {
        "market": config.market,
        "first": str(dates[0].date()),
        "last": str(dates[-1].date()),
        "holding_days": config.holding_days,
        "snapshots": len(dates),
        "schema": 1,
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:12]
    cache_dir = OUTPUT_DIR / "cache"
    return cache_dir / f"monthly_panel_{key}.pkl", cache_dir / f"monthly_panel_{key}.json"


def load_or_build_panel(config: Config, dates: list[pd.Timestamp], use_cache: bool = True) -> pd.DataFrame:
    data_path, metadata_path = _cache_paths(config, dates)
    if use_cache and data_path.exists() and metadata_path.exists():
        print(f"Loading cached panel: {data_path}", flush=True)
        return pd.read_pickle(data_path)
    panel = load_panel(config, dates)
    if use_cache:
        data_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = data_path.with_suffix(".tmp")
        panel.to_pickle(temporary)
        temporary.replace(data_path)
        metadata_path.write_text(
            json.dumps({"rows": len(panel), "dates": len(dates), "config": asdict(config)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Cached panel: {data_path}", flush=True)
    return panel


def matured_train_dates(dates: list[pd.Timestamp], period: int, train_periods: int) -> list[pd.Timestamp]:
    """Return only dates whose T+1..T+22 label has matured by this period."""

    usable_end = period - 2
    usable_start = max(0, usable_end - train_periods)
    return dates[usable_start:usable_end] if usable_end > 0 else []


def _prepare_train(panel: pd.DataFrame, dates: list[pd.Timestamp], config: Config) -> pd.DataFrame:
    parts = []
    for date in dates:
        part = prepare_snapshot(panel.xs(date, level="datetime"), config, require_label=True)
        if part.empty:
            continue
        part = part.copy()
        part["datetime"] = date
        parts.append(part.set_index("datetime", append=True).reorder_levels(["datetime", "instrument"]))
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts).sort_index()


def _fit_model(features: pd.DataFrame, target: pd.Series, seed: int) -> lgb.LGBMRegressor:
    dates = features.index.get_level_values("datetime")
    age_days = (dates.max() - dates).days.to_numpy()
    weights = np.exp(-np.log(2.0) * age_days / 504.0)
    model = lgb.LGBMRegressor(
        objective="regression",
        n_estimators=140,
        learning_rate=0.035,
        num_leaves=31,
        max_depth=6,
        min_child_samples=80,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_alpha=1.0,
        reg_lambda=8.0,
        random_state=seed,
        n_jobs=4,
        verbosity=-1,
    )
    model.fit(features, target, sample_weight=weights)
    return model


def _portfolio_row(
    strategy: str,
    instruments: list[str],
    current: pd.DataFrame,
    previous: set[str],
    date: pd.Timestamp,
    period: int,
    config: Config,
) -> tuple[dict[str, Any], set[str]]:
    chosen = set(instruments)
    buy_turnover = len(chosen - previous) / max(len(chosen), 1)
    sell_turnover = len(previous - chosen) / max(len(previous), 1)
    cost = buy_turnover * config.open_cost + sell_turnover * config.close_cost
    realized = current["forward_21"].reindex(instruments)
    gross = float(realized.fillna(-1.0).mean())
    return (
        {
            "signal_date": date,
            "period": period,
            "strategy": strategy,
            "n_holdings": len(instruments),
            "universe_size": len(current),
            "gross_return": gross,
            "cost": cost,
            "net_return": (1.0 + gross) * (1.0 - cost) - 1.0,
            "buy_turnover": buy_turnover,
            "sell_turnover": sell_turnover,
            "missing_returns": int(realized.isna().sum()),
        },
        chosen,
    )


def run_oos(
    panel: pd.DataFrame,
    dates: list[pd.Timestamp],
    config: Config,
    expressions: list[FactorExpression] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, FactorRegistry]:
    expressions = expressions or DeterministicGenerator().generate(BASE_FEATURES, config.candidate_limit)
    expression_map = {expression.name: expression for expression in expressions}
    registry = FactorRegistry()
    previous = {name: set() for name in ("auto_factor_lgb", "static_base_lgb", "eligible_equal_weight")}
    period_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    pending_factor_scores: dict[int, dict[str, pd.Series]] = {}

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
        train = _prepare_train(panel, train_dates, config)
        current = prepare_snapshot(panel.xs(date, level="datetime"), config, require_label=False)
        if train.empty or len(current) < config.top_n:
            continue

        ranked_train = rank_factor_matrix(train, expressions)
        metrics = evaluate_candidates(ranked_train, train["forward_21"], expressions)
        selected = select_diverse_factors(
            metrics,
            ranked_train,
            count=config.factor_count,
            max_abs_correlation=config.max_factor_correlation,
            min_abs_ic=config.min_abs_ic,
        )
        if not selected:
            selected = metrics.dropna(subset=["score"]).head(min(3, config.factor_count))["name"].tolist()
        registry.update(metrics, selected, date)
        orientations = metrics.set_index("name")["orientation"].astype(float)

        selected_expressions = [expression_map[name] for name in selected]
        current_ranked = rank_factor_matrix(current, selected_expressions)
        pending_factor_scores[period] = {
            name: (current_ranked[name] * float(orientations[name])).rename(name) for name in selected
        }
        auto_train = ranked_train[selected].mul(orientations[selected], axis=1)
        auto_current = current_ranked[selected].mul(orientations[selected], axis=1)
        # Keep expressive DSL names in audit outputs, but LightGBM rejects JSON
        # punctuation such as parentheses and commas in feature names.
        model_columns = [f"factor_{number:03d}" for number in range(len(selected))]
        auto_train.columns = model_columns
        auto_current.columns = model_columns
        target = train["forward_21"].groupby(level="datetime").rank(pct=True) - 0.5
        auto_model = _fit_model(auto_train, target, config.seed + period * 2)
        auto_score = pd.Series(auto_model.predict(auto_current), index=current.index)

        base_expressions = [FactorExpression("base", name) for name in BASE_FEATURES]
        static_train = ranked_train[list(BASE_FEATURES)]
        static_current = rank_factor_matrix(current, base_expressions)
        static_model = _fit_model(static_train, target, config.seed + period * 2 + 1)
        static_score = pd.Series(static_model.predict(static_current), index=current.index)
        portfolios = {
            "auto_factor_lgb": auto_score.nlargest(config.top_n).index.tolist(),
            "static_base_lgb": static_score.nlargest(config.top_n).index.tolist(),
            "eligible_equal_weight": current.index.tolist(),
        }
        for strategy, instruments in portfolios.items():
            row, previous[strategy] = _portfolio_row(
                strategy, instruments, current, previous[strategy], date, period, config
            )
            period_rows.append(row)

        metric_map = metrics.set_index("name")
        for rank, name in enumerate(selected, 1):
            metric = metric_map.loc[name]
            selection_rows.append(
                {
                    "signal_date": date,
                    "rank": rank,
                    "factor": name,
                    "orientation": int(metric["orientation"]),
                    "mean_ic": metric["mean_ic"],
                    "ic_ir": metric["ic_ir"],
                    "score": metric["score"],
                }
            )
        print(
            f"  OOS {date.date()} train={train_dates[0].date()}..{train_dates[-1].date()} "
            f"selected={len(selected)} best={selected[0]}",
            flush=True,
        )

    periods = pd.DataFrame(period_rows)
    if periods.empty:
        raise ValueError("No OOS periods were produced")
    return periods.sort_values(["signal_date", "strategy"]).reset_index(drop=True), pd.DataFrame(selection_rows), registry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automatic factor factory strict OOS backtest")
    parser.add_argument("--start", default=Config.start)
    parser.add_argument("--end", default=Config.end)
    parser.add_argument("--market", default=Config.market)
    parser.add_argument("--top-n", type=int, default=Config.top_n)
    parser.add_argument("--train-periods", type=int, default=Config.train_periods)
    parser.add_argument("--min-train-periods", type=int, default=Config.min_train_periods)
    parser.add_argument("--candidate-limit", type=int, default=Config.candidate_limit)
    parser.add_argument("--factor-count", type=int, default=Config.factor_count)
    parser.add_argument("--bootstrap-samples", type=int, default=Config.bootstrap_samples)
    parser.add_argument("--no-cache", action="store_true")
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    config = Config(
        market=args.market,
        start=args.start,
        end=args.end,
        top_n=args.top_n,
        train_periods=args.train_periods,
        min_train_periods=args.min_train_periods,
        candidate_limit=args.candidate_limit,
        factor_count=args.factor_count,
        bootstrap_samples=args.bootstrap_samples,
    )
    dates = signal_dates(calendar(), config)
    print(f"Loading {config.market}: {dates[0].date()}..{dates[-1].date()} ({len(dates)} snapshots)", flush=True)
    panel = load_or_build_panel(config, dates, use_cache=not args.no_cache)
    periods, selections, registry = run_oos(panel, dates, config)
    normal = summarize(periods, config, cost_multiplier=1.0)
    double = summarize(periods, config, cost_multiplier=2.0)
    subperiods = subperiod_summary(periods, config)
    frequencies = (
        selections.groupby("factor", as_index=False)
        .agg(selected_periods=("signal_date", "size"), mean_training_ic=("mean_ic", "mean"), mean_score=("score", "mean"))
        .sort_values(["selected_periods", "mean_score"], ascending=False)
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_DIR / "auto_factor" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    periods.to_csv(out_dir / "oos_periods.csv", index=False, encoding="utf-8-sig")
    selections.to_csv(out_dir / "factor_selections.csv", index=False, encoding="utf-8-sig")
    normal.to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig")
    double.to_csv(out_dir / "summary_double_cost.csv", index=False, encoding="utf-8-sig")
    subperiods.to_csv(out_dir / "subperiods.csv", index=False, encoding="utf-8-sig")
    frequencies.to_csv(out_dir / "factor_frequency.csv", index=False, encoding="utf-8-sig")
    (out_dir / "factor_registry.json").write_text(
        json.dumps(_json_safe(registry.snapshot()), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    payload = _json_safe(
        {
            "run": stamp,
            "config": asdict(config),
            "method": {
                "generator": "serialisable deterministic DSL; RD-Agent adapter boundary",
                "evaluation": "trailing matured labels only; RankIC scoring; greedy correlation deduplication",
                "model": "LightGBM retrained every 21 sessions on currently selected factors",
                "timing": "T close signal; T+1 open entry; T+22 open exit",
                "universe": "point-in-time CSI 800 membership with liquidity/tradability filters",
            },
            "summary": normal.to_dict("records"),
            "summary_double_cost": double.to_dict("records"),
            "subperiods": subperiods.to_dict("records"),
            "top_factor_frequency": frequencies.head(20).to_dict("records"),
            "output_dir": str(out_dir),
        }
    )
    (out_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "auto_factor_latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(normal.to_string(index=False), flush=True)
    print(f"Result: {out_dir / 'result.json'}", flush=True)
    return payload


if __name__ == "__main__":
    main()
