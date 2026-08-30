"""Strict rolling out-of-sample multi-expert backtest on CSI 800.

The experiment implements a small, auditable mixture-of-experts design:

* three LightGBM experts see different feature families;
* every prediction is made by models fitted only on fully matured history;
* the dynamic router uses only already-realized OOS RankIC observations;
* signals are formed at T close, entered at T+1 open, and held 21 sessions;
* CSI 800 membership is point-in-time and explicit trading costs are charged.

This is a research backtest.  It does not model partial fills or locked-limit exits.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from config import OUTPUT_DIR
from factor_transfer_backtest import (
    RawQlibStore,
    _bootstrap_mean_ci,
    _json_safe,
    _max_drawdown,
    calendar,
    point_in_time_members,
)


EXPERT_FEATURES = {
    "reversal": ["ret_5", "ret_20", "range_20", "vol_20", "amount_ratio"],
    "trend": ["ret_60", "mom_6_1", "mom_12_1", "amount_ratio", "vol_60"],
    "defensive": ["vol_20", "vol_60", "downside_60", "mom_6_1", "mom_12_1"],
}
ALL_FEATURES = sorted({feature for values in EXPERT_FEATURES.values() for feature in values})


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
    router_lookback: int = 12
    router_min_history: int = 6
    router_temperature: float = 8.0
    router_floor: float = 0.10
    seed: int = 20260717
    bootstrap_samples: int = 5000


def signal_dates(cal: pd.DatetimeIndex, config: Config) -> list[pd.Timestamp]:
    first = int(cal.searchsorted(pd.Timestamp(config.start), side="left"))
    requested_last = int(cal.searchsorted(pd.Timestamp(config.end), side="right")) - 1
    last = min(requested_last, len(cal) - config.holding_days - 2)
    if first > last:
        raise ValueError("No signal dates remain after reserving the forward window")
    return [pd.Timestamp(cal[i]) for i in range(first, last + 1, config.holding_days)]


def _finite_return(new: float, old: float) -> float:
    if not np.isfinite(new) or not np.isfinite(old) or old <= 0:
        return np.nan
    return float(new / old - 1.0)


def _safe_std(values: np.ndarray, minimum: int) -> float:
    clean = values[np.isfinite(values)]
    return float(clean.std(ddof=0)) if len(clean) >= minimum else np.nan


def load_panel(config: Config, dates: list[pd.Timestamp]) -> pd.DataFrame:
    cal = calendar()
    positions = {date: int(cal.searchsorted(date)) for date in dates}
    memberships = point_in_time_members(config.market, dates)
    store = RawQlibStore()
    records: list[dict[str, Any]] = []

    for number, date in enumerate(dates, 1):
        t = positions[date]
        members = memberships[date]
        if number == 1 or number % 12 == 0:
            print(f"  snapshot {number}/{len(dates)}: {date.date()} ({len(members)} members)", flush=True)
        for instrument in members:
            start, end = t - 252, t + 22
            close = store.window(instrument, "close", start, end)
            open_ = store.window(instrument, "open", start, end)
            high = store.window(instrument, "high", start, end)
            low = store.window(instrument, "low", start, end)
            volume = store.window(instrument, "volume", start, end)
            amount = store.window(instrument, "amount", start, end)
            now = 252

            returns_60 = close[now - 59 : now + 1] / close[now - 60 : now] - 1.0
            negative = returns_60[np.isfinite(returns_60) & (returns_60 < 0)]
            amount_recent = amount[now - 19 : now + 1]
            amount_prior = amount[now - 79 : now - 19]
            recent_mean = float(np.nanmean(amount_recent)) if np.isfinite(amount_recent).any() else np.nan
            prior_mean = float(np.nanmean(amount_prior)) if np.isfinite(amount_prior).any() else np.nan
            high_20 = high[now - 19 : now + 1]
            low_20 = low[now - 19 : now + 1]

            entry_open = float(open_[now + 1])
            entry_high = float(high[now + 1])
            entry_low = float(low[now + 1])
            exit_open = float(open_[now + 22])
            records.append(
                {
                    "instrument": instrument,
                    "datetime": date,
                    "ret_5": _finite_return(close[now], close[now - 5]),
                    "ret_20": _finite_return(close[now], close[now - 20]),
                    "ret_60": _finite_return(close[now], close[now - 60]),
                    "mom_6_1": _finite_return(close[now - 21], close[now - 126]),
                    "mom_12_1": _finite_return(close[now - 21], close[now - 252]),
                    "vol_20": _safe_std(returns_60[-20:], 15),
                    "vol_60": _safe_std(returns_60, 50),
                    "downside_60": _safe_std(negative, 10),
                    "range_20": (
                        float(np.nanmax(high_20) / np.nanmin(low_20) - 1.0)
                        if np.isfinite(high_20).any() and np.isfinite(low_20).any() and np.nanmin(low_20) > 0
                        else np.nan
                    ),
                    "amount_20": recent_mean,
                    "amount_ratio": _finite_return(recent_mean, prior_mean),
                    "close": float(close[now]),
                    "entry_open": entry_open,
                    "entry_high": entry_high,
                    "entry_low": entry_low,
                    "entry_volume": float(volume[now + 1]),
                    "forward_21": _finite_return(exit_open, entry_open),
                }
            )

    return pd.DataFrame(records).set_index(["datetime", "instrument"]).sort_index()


def prepare_snapshot(snapshot: pd.DataFrame, config: Config, require_label: bool) -> pd.DataFrame:
    frame = snapshot.copy()
    numeric_columns = frame.select_dtypes(include=[np.number]).columns
    frame.loc[:, numeric_columns] = frame[numeric_columns].replace([np.inf, -np.inf], np.nan)
    required = ALL_FEATURES + ["amount_20", "close", "entry_open", "entry_volume"]
    if require_label:
        required.append("forward_21")
    frame = frame.dropna(subset=required)
    if frame.empty:
        return frame

    liquidity_floor = frame["amount_20"].quantile(config.liquidity_quantile)
    frame = frame.loc[
        (frame["amount_20"] >= liquidity_floor)
        & (frame["close"] >= config.min_price)
        & (frame["entry_volume"] > 0)
    ].copy()
    locked_up = (
        np.isclose(frame["entry_open"], frame["entry_high"], rtol=1e-5, atol=1e-8)
        & np.isclose(frame["entry_open"], frame["entry_low"], rtol=1e-5, atol=1e-8)
        & (frame["entry_open"] / frame["close"] - 1.0 >= 0.095)
    )
    return frame.loc[~locked_up].copy()


def cross_sectional_rank(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame[columns].copy()
    for column in columns:
        result[column] = result.groupby(level="datetime")[column].rank(pct=True)
    return result


def fit_expert(
    train: pd.DataFrame,
    features: list[str],
    seed: int,
) -> lgb.LGBMRegressor:
    dates = train.index.get_level_values("datetime")
    age = dates.max() - dates
    weights = np.exp(-np.log(2.0) * age.days.to_numpy() / 504.0)
    model = lgb.LGBMRegressor(
        objective="regression",
        n_estimators=160,
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
    model.fit(train[features], train["target"], sample_weight=weights)
    return model


def router_weights(
    history: dict[str, list[float]],
    config: Config,
) -> dict[str, float]:
    names = list(EXPERT_FEATURES)
    if min(len(history[name]) for name in names) < config.router_min_history:
        return {name: 1.0 / len(names) for name in names}
    quality = np.array(
        [np.nanmean(history[name][-config.router_lookback :]) for name in names],
        dtype=float,
    )
    quality = np.nan_to_num(quality, nan=0.0)
    logits = config.router_temperature * (quality - quality.max())
    raw = np.exp(logits)
    raw /= raw.sum()
    floor = config.router_floor
    adjusted = floor + (1.0 - floor * len(names)) * raw
    return dict(zip(names, adjusted.tolist()))


def _spearman(scores: pd.Series, returns: pd.Series) -> float:
    aligned = pd.concat([scores.rename("score"), returns.rename("return")], axis=1).dropna()
    if len(aligned) < 20:
        return np.nan
    return float(aligned["score"].corr(aligned["return"], method="spearman"))


def run_oos(panel: pd.DataFrame, dates: list[pd.Timestamp], config: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    strategies = list(EXPERT_FEATURES) + ["equal_router", "dynamic_router", "eligible_equal_weight"]
    previous = {name: set() for name in strategies}
    oos_ic_history = {name: [] for name in EXPERT_FEATURES}
    pending_scores: dict[int, dict[str, pd.Series]] = {}
    period_rows: list[dict[str, Any]] = []
    weight_rows: list[dict[str, Any]] = []

    for period, date in enumerate(dates):
        # The score made two snapshots ago has completed its T+1..T+22 holding window.
        matured = pending_scores.pop(period - 2, None)
        if matured is not None:
            matured_date = dates[period - 2]
            realized = panel.xs(matured_date, level="datetime")["forward_21"]
            for name, score in matured.items():
                value = _spearman(score, realized)
                if np.isfinite(value):
                    oos_ic_history[name].append(value)

        if period < config.min_train_periods + 2:
            continue
        # Exclude the latest two snapshots because their 21-session labels are not known at T.
        usable_end = period - 2
        usable_start = max(0, usable_end - config.train_periods)
        train_dates = dates[usable_start:usable_end]
        if len(train_dates) < config.min_train_periods:
            continue

        train_parts = []
        for train_date in train_dates:
            part = prepare_snapshot(panel.xs(train_date, level="datetime"), config, require_label=True)
            if not part.empty:
                part = part.copy()
                part["datetime"] = train_date
                part = part.set_index("datetime", append=True).reorder_levels(["datetime", "instrument"])
                train_parts.append(part)
        if not train_parts:
            continue
        train = pd.concat(train_parts).sort_index()
        ranked_features = cross_sectional_rank(train, ALL_FEATURES)
        train.loc[:, ALL_FEATURES] = ranked_features
        train["target"] = train.groupby(level="datetime")["forward_21"].rank(pct=True) - 0.5

        current = prepare_snapshot(panel.xs(date, level="datetime"), config, require_label=False)
        if len(current) < config.top_n:
            continue
        current_features = current[ALL_FEATURES].rank(pct=True)
        expert_scores: dict[str, pd.Series] = {}
        for expert_number, (name, features) in enumerate(EXPERT_FEATURES.items()):
            model = fit_expert(train, features, config.seed + period * 10 + expert_number)
            raw = pd.Series(model.predict(current_features[features]), index=current.index)
            expert_scores[name] = raw.rank(pct=True).rename(name)

        pending_scores[period] = expert_scores
        equal_score = pd.concat(expert_scores, axis=1).mean(axis=1).rank(pct=True)
        weights = router_weights(oos_ic_history, config)
        dynamic_score = sum(expert_scores[name] * weights[name] for name in EXPERT_FEATURES).rank(pct=True)
        scores_by_strategy = expert_scores | {
            "equal_router": equal_score,
            "dynamic_router": dynamic_score,
        }
        weight_rows.append({"signal_date": date, **weights, **{f"history_{k}": len(v) for k, v in oos_ic_history.items()}})

        portfolios = {
            name: score.nlargest(config.top_n).index.tolist()
            for name, score in scores_by_strategy.items()
        }
        portfolios["eligible_equal_weight"] = current.index.tolist()

        for strategy, instruments in portfolios.items():
            old = previous[strategy]
            chosen = set(instruments)
            buy_turnover = len(chosen - old) / max(len(chosen), 1)
            sell_turnover = len(old - chosen) / max(len(old), 1)
            cost = buy_turnover * config.open_cost + sell_turnover * config.close_cost
            realized = current["forward_21"].reindex(instruments)
            missing_returns = int(realized.isna().sum())
            # A missing exit after a valid entry is treated as a total loss, avoiding survivor filtering.
            gross = float(realized.fillna(-1.0).mean())
            net = (1.0 + gross) * (1.0 - cost) - 1.0
            period_rows.append(
                {
                    "signal_date": date,
                    "period": period,
                    "strategy": strategy,
                    "n_holdings": len(instruments),
                    "universe_size": len(current),
                    "gross_return": gross,
                    "cost": cost,
                    "net_return": net,
                    "buy_turnover": buy_turnover,
                    "sell_turnover": sell_turnover,
                    "missing_returns": missing_returns,
                }
            )
            previous[strategy] = chosen

        print(
            f"  OOS {date.date()} train={train_dates[0].date()}..{train_dates[-1].date()} "
            f"weights=" + ",".join(f"{k}:{v:.2f}" for k, v in weights.items()),
            flush=True,
        )

    periods = pd.DataFrame(period_rows).sort_values(["signal_date", "strategy"]).reset_index(drop=True)
    weights = pd.DataFrame(weight_rows)
    if periods.empty:
        raise ValueError("No OOS periods were produced")
    return periods, weights


def summarize(periods: pd.DataFrame, config: Config, cost_multiplier: float = 1.0) -> pd.DataFrame:
    adjusted = periods.copy()
    extra_cost = adjusted["cost"] * (cost_multiplier - 1.0)
    adjusted["return"] = (1.0 + adjusted["net_return"]) * (1.0 - extra_cost) - 1.0
    pivot = adjusted.pivot(index="signal_date", columns="strategy", values="return")
    benchmark = pivot["eligible_equal_weight"]
    periods_per_year = 252 / config.holding_days
    rng = np.random.default_rng(config.seed + int(cost_multiplier * 100))
    rows = []
    for strategy in sorted(pivot.columns):
        returns = pivot[strategy].dropna()
        aligned = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
        excess = aligned.iloc[:, 0] - aligned.iloc[:, 1]
        annual_return = float((1.0 + returns).prod() ** (periods_per_year / len(returns)) - 1.0)
        annual_excess = float((1.0 + excess).prod() ** (periods_per_year / len(excess)) - 1.0)
        tracking_error = float(excess.std(ddof=1) * np.sqrt(periods_per_year))
        ci_low, ci_high = _bootstrap_mean_ci(excess.to_numpy(), rng, config.bootstrap_samples)
        rows.append(
            {
                "strategy": strategy,
                "periods": len(returns),
                "cost_multiplier": cost_multiplier,
                "annual_return_net": annual_return,
                "annual_excess_return": annual_excess,
                "information_ratio": annual_excess / tracking_error if tracking_error > 0 else np.nan,
                "endpoint_max_drawdown": _max_drawdown(returns),
                "excess_win_rate": float((excess > 0).mean()),
                "mean_period_excess": float(excess.mean()),
                "excess_mean_ci_2_5": ci_low,
                "excess_mean_ci_97_5": ci_high,
                "mean_one_way_turnover": float(
                    adjusted.loc[adjusted["strategy"] == strategy, ["buy_turnover", "sell_turnover"]]
                    .mean(axis=1)
                    .mean()
                ),
                "missing_exit_returns": int(adjusted.loc[adjusted["strategy"] == strategy, "missing_returns"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("annual_excess_return", ascending=False).reset_index(drop=True)


def subperiod_summary(periods: pd.DataFrame, config: Config) -> pd.DataFrame:
    rows = []
    for label, start, end in [("2018-2020", "2018-01-01", "2020-12-31"), ("2021-2023", "2021-01-01", "2023-12-31"), ("2024-2026", "2024-01-01", "2026-12-31")]:
        part = periods.loc[periods["signal_date"].between(start, end)]
        if part.empty:
            continue
        summary = summarize(part, config, cost_multiplier=1.0)
        for record in summary.to_dict("records"):
            rows.append({"subperiod": label, **record})
    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strict rolling OOS multi-expert backtest")
    parser.add_argument("--start", default=Config.start)
    parser.add_argument("--end", default=Config.end)
    parser.add_argument("--market", default=Config.market)
    parser.add_argument("--top-n", type=int, default=Config.top_n)
    parser.add_argument("--train-periods", type=int, default=Config.train_periods)
    parser.add_argument("--min-train-periods", type=int, default=Config.min_train_periods)
    parser.add_argument("--bootstrap-samples", type=int, default=Config.bootstrap_samples)
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
        bootstrap_samples=args.bootstrap_samples,
    )
    dates = signal_dates(calendar(), config)
    print(f"Loading {config.market}: {dates[0].date()}..{dates[-1].date()} ({len(dates)} snapshots)")
    panel = load_panel(config, dates)
    periods, weights = run_oos(panel, dates, config)
    normal = summarize(periods, config, cost_multiplier=1.0)
    double = summarize(periods, config, cost_multiplier=2.0)
    subperiods = subperiod_summary(periods, config)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_DIR / "multi_expert" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    periods.to_csv(out_dir / "oos_periods.csv", index=False, encoding="utf-8-sig")
    weights.to_csv(out_dir / "router_weights.csv", index=False, encoding="utf-8-sig")
    normal.to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig")
    double.to_csv(out_dir / "summary_double_cost.csv", index=False, encoding="utf-8-sig")
    subperiods.to_csv(out_dir / "subperiods.csv", index=False, encoding="utf-8-sig")

    payload = {
        "run": stamp,
        "config": asdict(config),
        "method": {
            "experts": EXPERT_FEATURES,
            "universe": "point-in-time CSI 800 membership",
            "timing": "T close signal; T+1 open entry; T+22 open exit",
            "anti_leakage": "models and router only use labels/OOS IC matured before signal time",
            "router": "bounded softmax of trailing realized OOS RankIC; equal weight during warm-up",
            "limitations": "monthly endpoints; no partial-fill or locked-limit exit state machine; no industry data",
        },
        "summary": normal.to_dict("records"),
        "summary_double_cost": double.to_dict("records"),
        "subperiods": subperiods.to_dict("records"),
        "output_dir": str(out_dir),
    }
    safe = _json_safe(payload)
    (out_dir / "result.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "multi_expert_latest.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(normal.to_string(index=False))
    print(f"Result: {out_dir / 'result.json'}")
    return safe


if __name__ == "__main__":
    main()
