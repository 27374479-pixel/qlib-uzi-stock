"""Leakage-safe 20/30 trading-day direction backtest for the candidate funnel.

The signal is formed at the close of T with information available no later than
T.  The executable proxy is the close of T+1 (the actual workflow enters near
that close after the 14:00 screen and UZI review).  Outcomes are measured from
that entry to the closes of T+21 and T+31, with explicit round-trip costs.

Forward returns are labels only: they are never read by ``score_snapshot`` or
``select_from_scored``.  Six staggered cohorts, each spaced 30 trading days
apart, are reported so overlapping 30-day labels are not mistaken for
independent evidence.
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

from candidate_funnel import FIELDS, FunnelConfig, get_calendar, init_qlib, score_snapshot, select_from_scored
from config import OUTPUT_DIR


LABEL_FIELDS = {
    "entry_close": "Ref($close,-1)",
    "forward_20d": "Ref($close,-21)/Ref($close,-1)-1",
    "forward_30d": "Ref($close,-31)/Ref($close,-1)-1",
}


@dataclass(frozen=True)
class DirectionBacktestConfig:
    start: str = "2021-01-01"
    end: str | None = None
    market: str = "csi800"
    base_top_n: int = 30
    uzi_queue_n: int = 8
    cohort_spacing: int = 30
    cohort_offsets: tuple[int, ...] = (0, 5, 10, 15, 20, 25)
    round_trip_cost: float = 0.0016


def load_direction_panel(config: DirectionBacktestConfig) -> pd.DataFrame:
    from qlib.data import D

    expressions = list(FIELDS.values()) + list(LABEL_FIELDS.values())
    names = list(FIELDS) + list(LABEL_FIELDS)
    panel = D.features(
        D.instruments(market=config.market),
        expressions,
        start_time=config.start,
        end_time=config.end,
        freq="day",
    )
    panel.columns = names
    panel.index = panel.index.set_names(["instrument", "datetime"])
    return panel.sort_index()


def cohort_dates(
    calendar: pd.DatetimeIndex,
    start: str,
    end: str,
    spacing: int,
    offset: int,
    forward_days: int = 31,
) -> list[pd.Timestamp]:
    start_position = int(calendar.searchsorted(pd.Timestamp(start), side="left"))
    end_position = int(calendar.searchsorted(pd.Timestamp(end), side="right")) - 1
    end_position = min(end_position, len(calendar) - forward_days - 1)
    first = start_position + offset
    if first > end_position:
        return []
    return [pd.Timestamp(calendar[position]) for position in range(first, end_position + 1, spacing)]


def _net_label(series: pd.Series, cost: float) -> pd.Series:
    return pd.to_numeric(series, errors="coerce") - cost


def _stats(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"dates": 0}
    result: dict[str, Any] = {"dates": int(frame["date"].nunique())}
    for horizon in (20, 30):
        column = f"return_{horizon}d"
        values = frame[column].dropna()
        date_returns = frame.groupby("date")[column].mean().dropna()
        result[f"{horizon}d"] = {
            "stock_predictions": int(len(values)),
            "stock_direction_accuracy": float((values > 0).mean()) if len(values) else None,
            "portfolio_direction_accuracy": float((date_returns > 0).mean()) if len(date_returns) else None,
            "portfolio_mean_return": float(date_returns.mean()) if len(date_returns) else None,
            "portfolio_median_return": float(date_returns.median()) if len(date_returns) else None,
            "portfolio_worst_return": float(date_returns.min()) if len(date_returns) else None,
        }
    paired = frame.dropna(subset=["return_20d", "return_30d"])
    per_date = paired.groupby("date")[["return_20d", "return_30d"]].mean()
    result["both_horizons_up_accuracy"] = (
        float(((per_date["return_20d"] > 0) & (per_date["return_30d"] > 0)).mean())
        if len(per_date)
        else None
    )
    return result


def evaluate_date(
    snapshot: pd.DataFrame,
    date: pd.Timestamp,
    funnel_config: FunnelConfig,
    queue_n: int,
    cost: float,
) -> list[dict[str, Any]]:
    scored = score_snapshot(snapshot, funnel_config)
    selected = select_from_scored(scored, funnel_config)
    queue = selected.head(queue_n)
    liquid = scored.loc[
        scored["liquidity20"] >= scored["liquidity20"].quantile(funnel_config.liquidity_quantile)
    ]
    momentum = liquid.sort_values("ret20", ascending=False).head(queue_n)
    healthy_breadth = (
        (liquid["close"] > liquid["ma20"])
        & (liquid["ma20"] > liquid["ma60"])
    ).mean()
    market_regime_ok = bool(healthy_breadth >= 0.55 and liquid["ret20"].median() > 0)
    volatility_ceiling = scored["vol20"].quantile(0.60)
    high_confidence = scored.loc[
        market_regime_ok
        & (scored["close"] > scored["ma20"])
        & (scored["ma20"] > scored["ma60"])
        & scored["ret20"].between(0.02, 0.20)
        & (scored["ret60"] > 0)
        & (scored["dist_ma20"] <= 0.10)
        & (scored["drawdown60"] >= -0.12)
        & (scored["vol20"] <= volatility_ceiling)
        & (scored["liquidity20"] >= scored["liquidity20"].quantile(funnel_config.liquidity_quantile))
        & scored["volume_ratio"].between(0.60, 2.00)
    ].sort_values("leader_score", ascending=False)
    high_confidence = high_confidence.head(queue_n) if len(high_confidence) >= 4 else high_confidence.iloc[0:0]
    strategies = {
        "uzi_queue_top8": queue,
        "high_confidence_or_abstain": high_confidence,
        "candidate_pool_top30": selected,
        "naive_momentum_top8": momentum,
        "liquid_market": liquid,
    }
    rows: list[dict[str, Any]] = []
    for strategy, holdings in strategies.items():
        for instrument, item in holdings.iterrows():
            rows.append(
                {
                    "date": str(date.date()),
                    "strategy": strategy,
                    "instrument": str(instrument),
                    "return_20d": float(item["forward_20d"] - cost) if pd.notna(item["forward_20d"]) else np.nan,
                    "return_30d": float(item["forward_30d"] - cost) if pd.notna(item["forward_30d"]) else np.nan,
                }
            )
    return rows


def run_backtest(config: DirectionBacktestConfig) -> dict[str, Any]:
    init_qlib()
    calendar = get_calendar()
    effective_end = config.end or str(pd.Timestamp(calendar[-1]).date())
    panel = load_direction_panel(DirectionBacktestConfig(**{**asdict(config), "end": effective_end}))
    funnel_config = FunnelConfig(market=config.market, top_n=config.base_top_n)

    cohort_reports: dict[str, Any] = {}
    all_rows: list[dict[str, Any]] = []
    for offset in config.cohort_offsets:
        dates = cohort_dates(
            calendar,
            config.start,
            effective_end,
            config.cohort_spacing,
            offset,
        )
        cohort_rows: list[dict[str, Any]] = []
        for date in dates:
            try:
                snapshot = panel.xs(date, level="datetime")
            except KeyError:
                continue
            rows = evaluate_date(snapshot, date, funnel_config, config.uzi_queue_n, config.round_trip_cost)
            for row in rows:
                row["cohort_offset"] = offset
            cohort_rows.extend(rows)
        cohort_frame = pd.DataFrame(cohort_rows)
        if not cohort_frame.empty:
            possible_dates = cohort_frame.loc[cohort_frame["strategy"] == "liquid_market", "date"].nunique()
            cohort_reports[str(offset)] = {}
            for strategy, group in cohort_frame.groupby("strategy"):
                report = _stats(group)
                report["coverage"] = float(report["dates"] / possible_dates) if possible_dates else None
                cohort_reports[str(offset)][strategy] = report
        else:
            cohort_reports[str(offset)] = {}
        all_rows.extend(cohort_rows)

    records = pd.DataFrame(all_rows)
    aggregate: dict[str, Any] = {}
    if not records.empty:
        possible_dates = records.loc[records["strategy"] == "liquid_market", "date"].nunique()
        for strategy, group in records.groupby("strategy"):
            report = _stats(group)
            report["coverage"] = float(report["dates"] / possible_dates) if possible_dates else None
            aggregate[strategy] = report
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": asdict(config),
        "methodology": {
            "signal": "T close, features use T and earlier daily data only",
            "entry_proxy": "T+1 close, approximating the post-14:00/UZI near-close entry",
            "labels": "T+1 close to T+21/T+31 close, less round-trip cost",
            "primary_metric": "equal-weight portfolio direction accuracy by signal date",
            "anti_leakage": "forward returns are evaluation labels and never enter scoring",
            "anti_overfit": "fixed funnel; no fit or parameter search; six staggered non-overlapping cohorts",
            "abstention": "high-confidence strategy emits no candidate unless breadth and individual trend gates pass",
            "uzi_limitation": "UZI is not historically replayed; top 8 is the queue sent to UZI",
        },
        "aggregate_overlapping_cohorts": aggregate,
        "independent_cohorts": cohort_reports,
        "records": all_rows,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest 20/30-day candidate direction accuracy")
    parser.add_argument("--start", default=DirectionBacktestConfig.start)
    parser.add_argument("--end")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "medium_term_direction_backtest.json")
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    result = run_backtest(DirectionBacktestConfig(start=args.start, end=args.end))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["aggregate_overlapping_cohorts"], ensure_ascii=False, indent=2))
    print(f"result: {args.output}")
    return result


if __name__ == "__main__":
    main()
