"""Strict OOS experiment: champion enriched model vs champion + industry breadth.

This script runs the identical enriched_factor_backtest pipeline twice:
once with the original 16 features (10 price-volume + 6 auxiliary), and once
with 18 features (+industry_new_high_breadth, +cross_industry_diffusion).

Both runs share the same panel, dates, and random seeds so the only difference
is the presence of the two breadth factors.  The output includes a frozen
comparison and a research report.
"""

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
from enriched_factor_backtest import (
    ALL_CANDIDATE_BASES,
    ENRICHED_FEATURES,
    Config,
    enrich_panel,
    prepare_enriched_snapshot,
    prepare_train,
    style_neutralize_score,
)
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
from industry_breadth_factor import BREADTH_FEATURES, compute_breadth_panel
from multi_expert_oos_backtest import prepare_snapshot, signal_dates, subperiod_summary, summarize


BREADTH_CANDIDATE_BASES = ALL_CANDIDATE_BASES + BREADTH_FEATURES


def enrich_with_breadth(
    panel: pd.DataFrame,
    dates: list[pd.Timestamp],
    market: str,
    cache_path: Path | None = None,
) -> pd.DataFrame:
    breadth_cache = cache_path.with_name(
        cache_path.stem + "_breadth.pkl"
    ) if cache_path else None
    breadth = compute_breadth_panel(dates, market=market, cache_path=breadth_cache)
    return panel.join(breadth, how="left")


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


def run_arm(
    arm_name: str,
    panel: pd.DataFrame,
    dates: list[pd.Timestamp],
    config: Config,
    candidate_bases: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame, FactorRegistry]:
    """Run one arm of the A/B experiment."""

    expressions_list = BalancedGenerator().generate(candidate_bases, config.candidate_limit)
    expressions = {e.name: e for e in expressions_list}
    registry = FactorRegistry()
    strategies = (f"{arm_name}_lgb", f"{arm_name}_neutral", "eligible_equal_weight")
    previous: dict[str, set] = {s: set() for s in strategies}
    pending: dict[int, dict[str, pd.Series]] = {}
    period_rows: list[dict] = []
    selection_rows: list[dict] = []

    for period, date in enumerate(dates):
        matured = pending.pop(period - 2, None)
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
        selected = select_diverse_factors(
            oos_metrics, ranked_train, config.factor_count, config.max_factor_correlation,
            config.min_abs_ic, expressions=expressions, max_per_family=4,
        )
        if not selected:
            continue

        registry.update(oos_metrics, selected, date)
        target = train["forward_21"].groupby(level="datetime").rank(pct=True) - 0.5

        score, current_ranked = _model_scores(
            ranked_train, current, expressions, oos_metrics, selected, target,
            config.seed + period * 10,
        )
        neutral_score = style_neutralize_score(score, current)
        orientations = oos_metrics.set_index("name")["orientation"]
        pending[period] = {
            name: (current_ranked[name] * float(orientations[name])).rename(name)
            for name in selected
        }

        scores = {f"{arm_name}_lgb": score, f"{arm_name}_neutral": neutral_score}
        portfolios = {name: val.nlargest(config.top_n).index.tolist() for name, val in scores.items()}
        portfolios["eligible_equal_weight"] = current.index.tolist()

        for strategy, instruments in portfolios.items():
            row, previous[strategy] = _portfolio_row(
                strategy, instruments, current, previous[strategy], date, period, config,
            )
            row["holdings"] = "|".join(instruments)
            period_rows.append(row)

        metric_map = oos_metrics.set_index("name")
        for rank, name in enumerate(selected, 1):
            metric = metric_map.loc[name]
            selection_rows.append({
                "signal_date": date,
                "rank": rank,
                "factor": name,
                "mean_training_ic": metric["mean_ic"],
                "mean_matured_oos_ic": metric["mean_oos_ic"],
                "oos_observations": int(metric["oos_observations"]),
                "oos_multiplier": metric["oos_multiplier"],
                "score": metric["score"],
            })

        if period == 0 or (period + 1) % 10 == 0:
            print(f"  [{arm_name}] period {period+1}: {date.date()} top_factor={selected[0]}", flush=True)

    periods = pd.DataFrame(period_rows)
    if periods.empty:
        raise ValueError(f"No OOS periods produced for arm {arm_name}")
    return (
        periods.sort_values(["signal_date", "strategy"]).reset_index(drop=True),
        pd.DataFrame(selection_rows),
        registry,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Champion vs Breadth-enhanced challenger backtest")
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

    print("=== Building base panel ===", flush=True)
    base_panel = load_or_build_panel(config, dates)
    enriched_cache = OUTPUT_DIR / "cache" / (
        f"enriched_monthly_panel_{dates[0]:%Y%m%d}_{dates[-1]:%Y%m%d}_{len(dates)}.pkl"
    )
    enriched_panel = enrich_panel(base_panel, enriched_cache)

    print("=== Computing breadth factors ===", flush=True)
    breadth_panel = enrich_with_breadth(enriched_panel, dates, config.market, enriched_cache)

    print("\n=== ARM 1: Champion (original 16 features) ===", flush=True)
    champion_periods, champion_sel, champion_reg = run_arm(
        "champion", enriched_panel, dates, config, ALL_CANDIDATE_BASES,
    )

    print("\n=== ARM 2: Challenger (16 + 2 breadth features) ===", flush=True)
    challenger_periods, challenger_sel, challenger_reg = run_arm(
        "challenger", breadth_panel, dates, config, BREADTH_CANDIDATE_BASES,
    )

    champion_summary = summarize(champion_periods, config, cost_multiplier=1.0)
    champion_double = summarize(champion_periods, config, cost_multiplier=2.0)
    champion_sub = subperiod_summary(champion_periods, config)

    challenger_summary = summarize(challenger_periods, config, cost_multiplier=1.0)
    challenger_double = summarize(challenger_periods, config, cost_multiplier=2.0)
    challenger_sub = subperiod_summary(challenger_periods, config)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_DIR / "breadth_challenger" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, periods, sel, reg, summ, dbl, sub in [
        ("champion", champion_periods, champion_sel, champion_reg,
         champion_summary, champion_double, champion_sub),
        ("challenger", challenger_periods, challenger_sel, challenger_reg,
         challenger_summary, challenger_double, challenger_sub),
    ]:
        periods.to_csv(out_dir / f"{name}_periods.csv", index=False, encoding="utf-8-sig")
        sel.to_csv(out_dir / f"{name}_selections.csv", index=False, encoding="utf-8-sig")
        summ.to_csv(out_dir / f"{name}_summary.csv", index=False, encoding="utf-8-sig")
        dbl.to_csv(out_dir / f"{name}_summary_double_cost.csv", index=False, encoding="utf-8-sig")
        sub.to_csv(out_dir / f"{name}_subperiods.csv", index=False, encoding="utf-8-sig")
        (out_dir / f"{name}_registry.json").write_text(
            json.dumps(_json_safe(reg.snapshot()), ensure_ascii=False, indent=2), encoding="utf-8",
        )

    def _extract_lgb_row(summary_df: pd.DataFrame, arm: str) -> dict:
        lgb_rows = summary_df[summary_df["strategy"].str.contains(f"{arm}_lgb")]
        return lgb_rows.iloc[0].to_dict() if len(lgb_rows) else {}

    champ_lgb = _extract_lgb_row(champion_summary, "champion")
    chall_lgb = _extract_lgb_row(challenger_summary, "challenger")

    comparison = {
        "champion_annual_return": champ_lgb.get("annual_return_net"),
        "champion_max_drawdown": champ_lgb.get("endpoint_max_drawdown"),
        "champion_ir": champ_lgb.get("information_ratio"),
        "champion_turnover": champ_lgb.get("mean_one_way_turnover"),
        "challenger_annual_return": chall_lgb.get("annual_return_net"),
        "challenger_max_drawdown": chall_lgb.get("endpoint_max_drawdown"),
        "challenger_ir": chall_lgb.get("information_ratio"),
        "challenger_turnover": chall_lgb.get("mean_one_way_turnover"),
        "annual_return_delta": (
            (chall_lgb.get("annual_return_net") or 0) - (champ_lgb.get("annual_return_net") or 0)
        ),
        "drawdown_improvement": (
            (chall_lgb.get("endpoint_max_drawdown") or 0) - (champ_lgb.get("endpoint_max_drawdown") or 0)
        ),
    }

    breadth_freq = challenger_sel[
        challenger_sel["factor"].str.contains("industry_new_high_breadth|cross_industry_diffusion")
    ].groupby("factor", as_index=False).agg(
        selected_periods=("signal_date", "size"),
        mean_training_ic=("mean_training_ic", "mean"),
    )

    payload = _json_safe({
        "run": stamp,
        "config": asdict(config),
        "features": {
            "champion": list(ALL_CANDIDATE_BASES),
            "challenger_additions": list(BREADTH_FEATURES),
        },
        "comparison": comparison,
        "breadth_factor_usage": breadth_freq.to_dict("records") if len(breadth_freq) else [],
        "champion_summary": champion_summary.to_dict("records"),
        "challenger_summary": challenger_summary.to_dict("records"),
        "champion_subperiods": champion_sub.to_dict("records"),
        "challenger_subperiods": challenger_sub.to_dict("records"),
        "output_dir": str(out_dir),
    })

    (out_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (OUTPUT_DIR / "breadth_challenger_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    print("\n" + "=" * 70, flush=True)
    print("CHAMPION vs CHALLENGER COMPARISON", flush=True)
    print("=" * 70, flush=True)
    print(f"\n{'Metric':<30} {'Champion':>12} {'Challenger':>12} {'Delta':>12}", flush=True)
    print("-" * 66, flush=True)
    for label, key in [
        ("Annual Return (net)", "annual_return_net"),
        ("Max Drawdown", "endpoint_max_drawdown"),
        ("Information Ratio", "information_ratio"),
        ("Excess Win Rate", "excess_win_rate"),
        ("One-Way Turnover", "mean_one_way_turnover"),
    ]:
        cv = champ_lgb.get(key)
        xv = chall_lgb.get(key)
        delta = (xv or 0) - (cv or 0) if cv is not None and xv is not None else None
        print(
            f"{label:<30} {cv:>12.4f} {xv:>12.4f} {delta:>+12.4f}"
            if cv is not None and xv is not None
            else f"{label:<30} {'N/A':>12} {'N/A':>12} {'N/A':>12}",
            flush=True,
        )
    print(f"\nResult: {out_dir / 'result.json'}", flush=True)
    return payload


if __name__ == "__main__":
    main()
