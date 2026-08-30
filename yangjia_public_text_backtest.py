"""YJ-BOOK: a daily, public-text-derived proxy for 炒股养家.

The public material attributed to 炒股养家 is mostly forum posts and Q&A, not
a machine-readable trading system.  This module turns the most testable parts
into an explicit daily strategy:

* strong / weak-early / weak-middle / weak-late / transition phases;
* main-sector, secondary-sector and non-main-sector ranking;
* trial position first, then confirmation-based add;
* short holding periods in weak phases and longer holds for confirmed leaders;
* opportunity-cost replacement and a hard no-leverage execution ledger.

It is intentionally a separate experiment from YJ-EP.  Signals use the close
of T and execute at T+1 open.  Each daily realised return is T+1 open to the
following open, with commissions and known limit/suspension blocks applied.
The strategy does not claim to reproduce a discretionary trader's private
process or intraday information.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from config import OUTPUT_DIR, QLIB_DATA_DIR
from factor_transfer_backtest import (
    RawQlibStore,
    _bootstrap_mean_ci,
    _max_drawdown,
    calendar,
)
from yangjia_expectation_pressure_backtest import (
    AuxiliaryStore,
    IndustrySnapshots,
    PointInTimeUniverse,
    _json_safe,
    classify_regime,
    execute_target,
    load_snapshot,
    market_sentiment,
    prepare_snapshot,
    signal_dates,
)


STRATEGY_BOOK = "yj_book"
STRATEGY_BENCHMARK = "eligible_equal_weight"
STRATEGIES = [STRATEGY_BOOK, STRATEGY_BENCHMARK]

PHASE_STRONG = "strong"
PHASE_TRANSITION = "transition"
PHASE_WEAK_EARLY = "weak_early"
PHASE_WEAK_MIDDLE = "weak_middle"
PHASE_WEAK_LATE = "weak_late"


@dataclass(frozen=True)
class BookConfig:
    market: str = "csi800"
    start: str = "2015-01-05"
    end: str | None = None
    # Daily signals are required to model trial -> confirm -> add and short
    # weak-market exits.  The execution layer still uses next-open prices.
    rebalance_step: int = 1
    top_n: int = 15
    max_sector_names: int = 3
    hold_buffer: int = 3
    min_price: float = 2.0
    liquidity_quantile: float = 0.20
    open_cost: float = 0.0003
    close_cost: float = 0.0013
    strong_threshold: float = 0.60
    weak_threshold: float = 0.40
    seed: int = 20260823
    bootstrap_samples: int = 5000
    use_auxiliary: bool = True


def _clip01(value: pd.Series | np.ndarray | float) -> pd.Series | np.ndarray | float:
    return np.clip(value, 0.0, 1.0)


def _phase_from_sentiment(
    sentiment: dict[str, float],
    history: list[float],
    config: BookConfig,
) -> str:
    """Classify the phase without using any future score.

    The weak-market split follows the public Q&A distinction: early weakness
    still has rebound expectations, middle weakness is dominated by forced
    selling, and late weakness is where new money starts to show itself.
    """

    score = float(sentiment.get("sentiment_score", 0.5))
    observed = history + [score]
    delta_3 = score - observed[-4] if len(observed) >= 4 else 0.0
    delta_5 = score - observed[-6] if len(observed) >= 6 else 0.0
    improving = (
        delta_3 >= 0.045
        or delta_5 >= 0.065
        or (
            len(observed) >= 4
            and score >= min(observed[-4:]) + 0.075
        )
    )
    if score >= config.strong_threshold:
        return PHASE_STRONG
    if score > config.weak_threshold:
        return PHASE_TRANSITION

    if improving and (
        float(sentiment.get("advance_ratio", 0.5)) >= 0.43
        or float(sentiment.get("top_decile_ret_5", 0.0)) >= 0.035
    ):
        return PHASE_WEAK_LATE

    if (
        float(sentiment.get("median_ret_20", 0.0)) <= -0.12
        and float(sentiment.get("weak_ratio", 0.0)) >= 0.35
        and score <= 0.34
    ):
        return PHASE_WEAK_MIDDLE

    if delta_5 <= -0.055 or float(sentiment.get("median_ret_20", 0.0)) > -0.12:
        return PHASE_WEAK_EARLY
    return PHASE_WEAK_MIDDLE


def _book_exposure(phase: str, sentiment: dict[str, float]) -> float:
    """Base cash budget; new names only receive half until confirmed."""

    if phase == PHASE_STRONG:
        return 1.00
    if phase == PHASE_TRANSITION:
        return 0.35
    if phase == PHASE_WEAK_EARLY:
        return 0.20
    if phase == PHASE_WEAK_MIDDLE:
        return 0.08
    improvement = float(sentiment.get("advance_ratio", 0.5)) >= 0.45
    return 0.35 if improvement else 0.25


def add_public_text_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add proxies for mainline, followers, oversold repair and confirmation."""

    if frame.empty:
        return frame
    result = frame.copy()

    # Sector strength is deliberately based on point-in-time sector breadth
    # and returns, not on a future list of winning themes.
    result["sector_score"] = (
        0.45 * result["r_sector_strength"]
        + 0.35 * result["r_sector_breadth"]
        + 0.20 * result["sector_breadth_1"]
    )
    result["sector_percentile"] = result["sector_score"].rank(pct=True).fillna(0.5)
    result["sector_class"] = np.select(
        [result["sector_percentile"] >= 0.70, result["sector_percentile"] >= 0.40],
        ["main", "secondary"],
        default="non_main",
    )

    # A lower close_to_low_20 means the stock is nearer the low of its recent
    # range.  Descending rank therefore gives higher values to deeper selloffs.
    near_low_rank = result["close_to_low_20"].rank(pct=True, ascending=False).fillna(0.5)
    oversold = (
        0.50 * result["r_oversold_20"]
        + 0.25 * result["r_oversold_5"]
        + 0.25 * near_low_rank
    )
    repair_confirmation = (
        0.50 * result["r_ret_1"]
        + 0.25 * result["r_close_location"]
        + 0.25 * result["r_volume"]
    )
    result["deep_oversold_repair"] = oversold * (0.40 + 0.60 * repair_confirmation)

    result["follower_score"] = (
        0.50 * result["sector_score"]
        + 0.25 * (1.0 - result["r_stock_sector"])
        + 0.15 * result["r_ret_1"]
        + 0.10 * result["r_volume"]
    )
    result["mainline_leader_score"] = (
        0.35 * result["sector_score"]
        + 0.30 * result["r_stock_sector"]
        + 0.20 * result["r_ret_20"]
        + 0.10 * result["r_ret_1"]
        + 0.05 * result["r_volume"]
    )
    result["confirmation"] = (
        (result["ret_1"] > 0.0)
        & (result["relative_to_sector"] > -0.01)
        & (result["sector_breadth_1"] >= 0.45)
        & (result["volume_ratio"] >= 0.80)
    )
    result["not_overextended"] = (
        (result["ret_20"] < 0.55)
        | (result["ret_5"] < 0.20)
        | (result["close_location"] < 0.78)
    )
    result["book_eligible"] = result["signal_eligible"] & result["not_overextended"]
    return result


def public_text_score(frame: pd.DataFrame, phase: str) -> pd.Series:
    """Score candidates using the phase-specific public-text logic."""

    if phase == PHASE_STRONG:
        # Strong phase: new money is more likely to choose existing leaders;
        # followers in the main sector get a smaller expectation-gap term.
        return (
            0.55 * frame["mainline_leader_score"]
            + 0.25 * frame["sector_percentile"]
            + 0.10 * frame["follower_score"]
            + 0.10 * frame["r_ret_1"]
        )
    if phase == PHASE_WEAK_EARLY:
        return (
            0.55 * frame["controlled_pullback"]
            + 0.25 * frame["mainline_leader_score"]
            + 0.20 * frame["r_ret_1"]
        )
    if phase == PHASE_WEAK_MIDDLE:
        return (
            0.65 * frame["deep_oversold_repair"]
            + 0.20 * frame["panic_repair"]
            + 0.15 * frame["r_ret_1"]
        )
    if phase == PHASE_WEAK_LATE:
        return (
            0.50 * frame["mainline_leader_score"]
            + 0.30 * frame["sector_percentile"]
            + 0.20 * frame["r_ret_1"]
        )
    return (
        0.45 * frame["expectation_gap"]
        + 0.30 * frame["mainline_leader_score"]
        + 0.15 * frame["follower_score"]
        + 0.10 * frame["deep_oversold_repair"]
    )


def _phase_horizon(phase: str) -> int:
    return {
        PHASE_STRONG: 8,
        PHASE_TRANSITION: 3,
        PHASE_WEAK_EARLY: 2,
        PHASE_WEAK_MIDDLE: 1,
        PHASE_WEAK_LATE: 3,
    }[phase]


def select_public_text_names(
    frame: pd.DataFrame,
    phase: str,
    previous: set[str],
    ages: dict[str, int],
    config: BookConfig,
) -> tuple[list[str], pd.Series]:
    """Select a concentrated set and return its auditable score series."""

    if frame.empty:
        return [], pd.Series(dtype=float)
    candidates = frame.loc[frame["book_eligible"]].copy()
    if candidates.empty:
        return [], pd.Series(dtype=float)

    if phase == PHASE_WEAK_MIDDLE:
        # The middle-stage setup is intentionally selective.  If the filter
        # has no names, fall back to the ranked universe rather than fabricating
        # a look-ahead signal.
        repaired = candidates.loc[candidates["deep_oversold_repair"] >= 0.30]
        if not repaired.empty:
            candidates = repaired
    scores = public_text_score(candidates, phase).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    candidates = candidates.assign(selection_score=scores).sort_values(
        ["selection_score", "mainline_leader_score"], ascending=False
    )
    ranks = candidates["selection_score"].rank(method="first", ascending=False)
    horizon = _phase_horizon(phase)
    sticky = candidates.loc[
        candidates.index.isin(previous)
        & (ranks <= config.top_n + config.hold_buffer)
        & (~candidates["consensus_exhaustion"])
        & candidates.index.to_series().map(lambda name: ages.get(name, 0) < horizon)
    ]
    ordered = pd.concat([sticky, candidates.drop(index=sticky.index)])

    selected: list[str] = []
    sector_counts: dict[str, int] = {}
    for instrument, row in ordered.iterrows():
        sector = str(row["industry_code"])
        if sector_counts.get(sector, 0) >= config.max_sector_names:
            continue
        selected.append(str(instrument))
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected) >= config.top_n:
            break
    return selected, candidates["selection_score"]


def public_text_target(
    selected: list[str],
    phase: str,
    exposure: float,
    frame: pd.DataFrame,
    previous: dict[str, float],
) -> dict[str, float]:
    """Make new entries half-size and add only after a visible confirmation."""

    if not selected or exposure <= 0:
        return {}
    names = [name for name in selected if name in frame.index]
    if not names:
        return {}
    unit = exposure / len(names)
    desired: dict[str, float] = {}
    for name in names:
        row = frame.loc[name]
        old = float(previous.get(name, 0.0))
        confirmed = bool(row["confirmation"])
        if old > 1e-12 and confirmed:
            factor = 1.0
        elif old > 1e-12:
            # A position that has not confirmed is not automatically cut to
            # zero; it is reduced, which models “判断错时仍有应变优势”.
            factor = 0.50
        else:
            # First touch is a probe.  Subsequent daily confirmation can lift
            # it to the full per-name budget.
            factor = 0.50
        desired[name] = unit * factor
    return desired


def _target_weights(selected: list[str], exposure: float) -> dict[str, float]:
    if not selected or exposure <= 0:
        return {}
    weight = exposure / len(selected)
    return {name: weight for name in selected}


def _summary(periods: pd.DataFrame, config: BookConfig) -> pd.DataFrame:
    pivot = periods.pivot(index="signal_date", columns="strategy", values="net_return")
    benchmark = pivot[STRATEGY_BENCHMARK]
    rng = np.random.default_rng(config.seed)
    rows: list[dict[str, Any]] = []
    for strategy in pivot.columns:
        returns = pivot[strategy].dropna()
        if returns.empty:
            continue
        aligned = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
        excess = (aligned.iloc[:, 0] - aligned.iloc[:, 1]).to_numpy()
        annual_return = float((1.0 + returns).prod() ** (252.0 / len(returns)) - 1.0)
        annual_vol = float(returns.std(ddof=1) * np.sqrt(252.0)) if len(returns) > 1 else np.nan
        arithmetic_annual = float(returns.mean() * 252.0)
        sharpe = arithmetic_annual / annual_vol if np.isfinite(annual_vol) and annual_vol > 0 else np.nan
        mdd = _max_drawdown(returns)
        positive = returns[returns > 0].sum()
        negative = returns[returns < 0].sum()
        stats = periods.loc[periods["strategy"] == strategy]
        ci_low, ci_high = _bootstrap_mean_ci(excess, rng, config.bootstrap_samples)
        rows.append(
            {
                "strategy": strategy,
                "periods": int(len(returns)),
                "annual_return": annual_return,
                "annual_volatility": annual_vol,
                "sharpe": sharpe,
                "max_drawdown": mdd,
                "calmar": annual_return / abs(mdd) if mdd < 0 else np.nan,
                "win_rate": float((returns > 0).mean()),
                "profit_factor": float(positive / abs(negative)) if negative < 0 else np.nan,
                "mean_excess": float(np.mean(excess)) if len(excess) else np.nan,
                "excess_win_rate": float(np.mean(excess > 0)) if len(excess) else np.nan,
                "excess_ci_2.5": ci_low,
                "excess_ci_97.5": ci_high,
                "avg_exposure": float(stats["realised_exposure"].mean()),
                "avg_holdings": float(stats["n_holdings"].mean()),
                "mean_turnover": float(stats[["buy_turnover", "sell_turnover"]].sum(axis=1).mean()),
                "total_cost": float(stats["cost"].sum()),
                "blocked_change_rate": float(
                    stats["blocked_changes"].sum() / max(stats["requested_changes"].sum(), 1)
                ),
                "missing_return_count": int(stats["missing_returns"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("annual_return", ascending=False).reset_index(drop=True)


def _subperiods(periods: pd.DataFrame) -> pd.DataFrame:
    bins = [
        ("2015-2017", "2015-01-01", "2017-12-31"),
        ("2018-2020", "2018-01-01", "2020-12-31"),
        ("2021-2023", "2021-01-01", "2023-12-31"),
        ("2024-2026", "2024-01-01", "2026-12-31"),
    ]
    rows: list[dict[str, Any]] = []
    for label, start, end in bins:
        part = periods.loc[periods["signal_date"].between(start, end)]
        for strategy, group in part.groupby("strategy"):
            returns = group.sort_values("signal_date")["net_return"]
            if returns.empty:
                continue
            rows.append(
                {
                    "subperiod": label,
                    "strategy": strategy,
                    "periods": int(len(returns)),
                    "annual_return": float((1.0 + returns).prod() ** (252.0 / len(returns)) - 1.0),
                    "max_drawdown": _max_drawdown(returns),
                    "win_rate": float((returns > 0).mean()),
                    "avg_exposure": float(group["realised_exposure"].mean()),
                }
            )
    return pd.DataFrame(rows)


def run_backtest(config: BookConfig) -> dict[str, Any]:
    cal = calendar()
    dates = signal_dates(cal, config)
    date_positions = {date: int(cal.searchsorted(date)) for date in dates}
    universe = PointInTimeUniverse(config.market, dates)
    industries = IndustrySnapshots()
    store = RawQlibStore()
    auxiliary = AuxiliaryStore() if config.use_auxiliary else None

    previous: dict[str, float] = {}
    benchmark_previous: dict[str, float] = {}
    ages: dict[str, int] = {}
    score_history: list[float] = []
    period_rows: list[dict[str, Any]] = []
    sentiment_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []

    for number, date in enumerate(dates, 1):
        if number == 1 or number % 250 == 0 or number == len(dates):
            print(
                f"  [{number}/{len(dates)}] {date.date()} "
                f"({len(universe.at(number - 1))} members)",
                flush=True,
            )
        snapshot = load_snapshot(
            date=date,
            position=date_positions[date],
            members=universe.at(number - 1),
            industry_map=industries.at(date),
            store=store,
            auxiliary=auxiliary,
            forward_sessions=1,
        )
        frame = add_public_text_features(prepare_snapshot(snapshot, config))
        sentiment = market_sentiment(frame)
        phase = _phase_from_sentiment(sentiment, score_history, config)
        # Keep the original three-state classification in the audit trail so
        # the new weak-stage split can be compared with the existing YJ-EP.
        coarse_regime = classify_regime(sentiment, score_history[-1] if score_history else None, config)
        exposure = _book_exposure(phase, sentiment)
        selected, scores = select_public_text_names(frame, phase, set(previous), ages, config)
        desired = public_text_target(selected, phase, exposure, frame, previous)
        actual, blocked = execute_target(desired, previous, snapshot)
        if frame.empty:
            benchmark_desired = {}
        else:
            benchmark_desired = _target_weights(frame.index.tolist(), 1.0)
        benchmark_old = benchmark_previous
        benchmark_actual, benchmark_blocked = execute_target(
            benchmark_desired,
            benchmark_old,
            snapshot,
        )

        for strategy, weights, old, blocked_count, target in [
            (STRATEGY_BOOK, actual, previous, blocked, desired),
            (
                STRATEGY_BENCHMARK,
                benchmark_actual,
                benchmark_old,
                benchmark_blocked,
                benchmark_desired,
            ),
        ]:
            stats = _realised_period(weights, old, snapshot, config)
            requested_changes = sum(
                not np.isclose(target.get(name, 0.0), old.get(name, 0.0))
                for name in set(target) | set(old)
            )
            period_rows.append(
                {
                    "signal_date": date,
                    "execution_date": pd.Timestamp(cal[date_positions[date] + 1]),
                    "strategy": strategy,
                    "phase": phase,
                    "coarse_regime": coarse_regime,
                    "sentiment_score": sentiment["sentiment_score"],
                    "target_exposure": exposure if strategy == STRATEGY_BOOK else 1.0,
                    "n_holdings": len(weights),
                    "universe_size": len(frame),
                    "selected_names": len(selected) if strategy == STRATEGY_BOOK else len(frame),
                    "blocked_changes": blocked_count,
                    "requested_changes": requested_changes,
                    **stats,
                }
            )

        # Save benchmark state only after its cost/P&L values are computed.
        benchmark_previous = benchmark_actual
        for name in set(actual):
            ages[name] = ages.get(name, 0) + 1 if name in previous else 1
        ages = {name: age for name, age in ages.items() if name in actual}
        for name, row in frame.loc[frame.index.intersection(selected)].iterrows():
            audit_rows.append(
                {
                    "signal_date": date,
                    "phase": phase,
                    "instrument": name,
                    "industry_code": row["industry_code"],
                    "sector_class": row["sector_class"],
                    "selection_score": float(scores.get(name, np.nan)),
                    "confirmation": bool(row["confirmation"]),
                    "ret_1": float(row["ret_1"]),
                    "ret_5": float(row["ret_5"]),
                    "ret_20": float(row["ret_20"]),
                    "sector_percentile": float(row["sector_percentile"]),
                    "deep_oversold_repair": float(row["deep_oversold_repair"]),
                }
            )
        sentiment_rows.append(
            {
                "signal_date": date,
                "phase": phase,
                "coarse_regime": coarse_regime,
                "exposure": exposure,
                **sentiment,
            }
        )
        previous = actual
        score_history.append(float(sentiment["sentiment_score"]))

    periods = pd.DataFrame(period_rows).sort_values(["signal_date", "strategy"]).reset_index(drop=True)
    sentiments = pd.DataFrame(sentiment_rows)
    audit = pd.DataFrame(audit_rows)
    summary = _summary(periods, config)
    subperiods = _subperiods(periods)
    phase_rows = []
    for (strategy, phase), group in periods.groupby(["strategy", "phase"]):
        phase_rows.append(
            {
                "strategy": strategy,
                "phase": phase,
                "periods": int(len(group)),
                "mean_net_return": float(group["net_return"].mean()),
                "win_rate": float((group["net_return"] > 0).mean()),
                "avg_exposure": float(group["realised_exposure"].mean()),
            }
        )
    phase_summary = pd.DataFrame(phase_rows)

    output_dir = OUTPUT_DIR / "yangjia_public_text" / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    periods.to_csv(output_dir / "period_returns.csv", index=False)
    sentiments.to_csv(output_dir / "sentiment_history.csv", index=False)
    audit.to_csv(output_dir / "selection_audit.csv", index=False)
    summary.to_csv(output_dir / "summary.csv", index=False)
    subperiods.to_csv(output_dir / "subperiods.csv", index=False)
    phase_summary.to_csv(output_dir / "phase_summary.csv", index=False)

    results = {
        "run": output_dir.name,
        "config": asdict(config),
        "data": {
            "provider_uri": str(QLIB_DATA_DIR),
            "qlib_calendar_start": str(cal[0].date()),
            "qlib_calendar_end": str(cal[-1].date()),
            "signal_start": str(dates[0].date()),
            "signal_end": str(dates[-1].date()),
            "point_in_time_universe": config.market,
            "industry_snapshot_count": len(industries.dates),
            "auxiliary_root": str(auxiliary.root) if auxiliary else None,
        },
        "method": {
            "name": "YJ-BOOK v1 (public-text-derived daily adaptive strategy)",
            "source_boundary": "forum posts/Q&A attributed to 炒股养家; no verified author-published book/ISBN found",
            "phase_model": "strong; transition; weak early; weak middle; weak late",
            "strong_phase": "main-sector leaders plus lower-position followers; longer hold horizon",
            "weak_early": "pullback/rebound of previously strong names or new hot sectors",
            "weak_middle": "selective deep oversold repair after a further selloff",
            "weak_late": "mainline high-elasticity leaders after early money-making effect returns",
            "trial_confirm_add": "new names half-size; visible close/sector confirmation can add to full unit",
            "opportunity_cost_exit": "daily re-ranking with phase-dependent hold buffer; no cost anchoring",
            "execution": "T close signal -> T+1 open order -> T+2 open valuation; commissions and blocked orders",
            "future_data_policy": "all ranking fields use T and earlier; forward opens are execution outcomes only",
        },
        "phase_distribution": sentiments["phase"].value_counts().to_dict(),
        "summary": summary.to_dict(orient="records"),
        "phase_summary": phase_summary.to_dict(orient="records"),
        "output_dir": str(output_dir),
    }
    (output_dir / "results.json").write_text(
        json.dumps(_json_safe(results), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[output] {output_dir}", flush=True)
    print(summary.to_string(index=False), flush=True)
    return results


def _realised_period(
    weights: dict[str, float],
    previous: dict[str, float],
    snapshot: pd.DataFrame,
    config: BookConfig,
) -> dict[str, float | int]:
    buy = sum(max(weight - previous.get(name, 0.0), 0.0) for name, weight in weights.items())
    sell = sum(max(previous.get(name, 0.0) - weights.get(name, 0.0), 0.0) for name in previous)
    cost = buy * config.open_cost + sell * config.close_cost
    gross = 0.0
    missing = 0
    for name, weight in weights.items():
        if name not in snapshot.index:
            missing += 1
            continue
        entry = float(snapshot.at[name, "entry_open"])
        forward = float(snapshot.at[name, "next_open"])
        if not np.isfinite(entry) or not np.isfinite(forward) or entry <= 0:
            missing += 1
            continue
        gross += weight * (forward / entry - 1.0)
    net = (1.0 + gross) * (1.0 - cost) - 1.0
    return {
        "gross_return": gross,
        "cost": cost,
        "net_return": net,
        "buy_turnover": buy,
        "sell_turnover": sell,
        "missing_returns": missing,
        "realised_exposure": sum(weights.values()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YJ-BOOK 炒股养家公开原文阶段化回测")
    parser.add_argument("--market", default=BookConfig.market)
    parser.add_argument("--start", default=BookConfig.start)
    parser.add_argument("--end", default=None)
    parser.add_argument("--top-n", type=int, default=BookConfig.top_n)
    parser.add_argument("--max-sector-names", type=int, default=BookConfig.max_sector_names)
    parser.add_argument("--hold-buffer", type=int, default=BookConfig.hold_buffer)
    parser.add_argument("--bootstrap-samples", type=int, default=BookConfig.bootstrap_samples)
    parser.add_argument("--no-auxiliary", action="store_true")
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    config = BookConfig(
        market=args.market,
        start=args.start,
        end=args.end,
        top_n=args.top_n,
        max_sector_names=args.max_sector_names,
        hold_buffer=args.hold_buffer,
        bootstrap_samples=args.bootstrap_samples,
        use_auxiliary=not args.no_auxiliary,
    )
    print("=" * 72)
    print("  YJ-BOOK 炒股养家公开原文阶段化回测")
    print("=" * 72)
    print(f"  market={config.market} start={config.start} end={config.end or 'latest Qlib date'}")
    print(f"  daily signals top_n={config.top_n} auxiliary={config.use_auxiliary}")
    return run_backtest(config)


if __name__ == "__main__":
    main()
