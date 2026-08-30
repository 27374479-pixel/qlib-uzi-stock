"""Validate portable, price-based factor strategies on historical CSI 800 members.

The experiment is intentionally simple and auditable:

* signals are formed after the close on T;
* orders execute at T+1 open and positions are held for 21 trading days;
* the next signal is also 21 trading days later, so holding periods do not overlap;
* index membership is point-in-time (the local Qlib CSI 800 instrument ranges);
* one-price limit-up stocks at entry are skipped;
* reported returns include buy and sell costs and turnover.

This is a factor-transfer test, not a production execution simulator.  In particular,
drawdown is measured at 21-day portfolio endpoints and delisting/locked-limit exits
need a separate daily event-driven test before live use.
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

from config import OUTPUT_DIR, QLIB_DATA_DIR


FIELDS = {
    "ret_5": "$close/Ref($close,5)-1",
    "ret_20": "$close/Ref($close,20)-1",
    # Conventional cross-sectional momentum skips the most recent month.
    "mom_6_1": "Ref($close,21)/Ref($close,126)-1",
    "mom_12_1": "Ref($close,21)/Ref($close,252)-1",
    "vol_60": "Std($close/Ref($close,1)-1,60)",
    "amount_20": "Mean($amount,20)",
    "close": "$close",
    # T close signal -> T+1 open entry -> T+22 open exit (21 sessions).
    "forward_21": "Ref($open,-22)/Ref($open,-1)-1",
    "entry_open": "Ref($open,-1)",
    "entry_high": "Ref($high,-1)",
    "entry_low": "Ref($low,-1)",
    "entry_volume": "Ref($volume,-1)",
}


@dataclass(frozen=True)
class Config:
    market: str = "csi800"
    start: str = "2008-01-01"
    end: str = "2026-05-29"
    holding_days: int = 21
    top_n: int = 100
    liquidity_quantile: float = 0.20
    min_price: float = 2.0
    open_cost: float = 0.0003
    close_cost: float = 0.0013
    seed: int = 20260715
    bootstrap_samples: int = 10000


def init_qlib() -> None:
    import qlib
    from qlib.constant import REG_CN

    qlib.init(provider_uri=str(QLIB_DATA_DIR), region=REG_CN)


def calendar() -> pd.DatetimeIndex:
    path = QLIB_DATA_DIR / "calendars" / "day.txt"
    return pd.DatetimeIndex(pd.read_csv(path, header=None)[0]).sort_values()


def signal_dates(cal: pd.DatetimeIndex, config: Config) -> list[pd.Timestamp]:
    first = int(cal.searchsorted(pd.Timestamp(config.start), side="left"))
    last_requested = int(cal.searchsorted(pd.Timestamp(config.end), side="right")) - 1
    # A signal needs T+22 open in the local data.
    last = min(last_requested, len(cal) - config.holding_days - 2)
    if first > last:
        raise ValueError("No test dates remain after reserving the forward holding window")
    return [pd.Timestamp(cal[i]) for i in range(first, last + 1, config.holding_days)]


class RawQlibStore:
    """Small read-only loader for Qlib's float32 day-bin format.

    Qlib expression evaluation is convenient but unusually slow on the local Windows
    dataset because the CSI 800 membership file contains many short intervals.  This
    loader reads only the handful of points needed by this experiment.
    """

    def __init__(self) -> None:
        self.feature_root = QLIB_DATA_DIR / "features"
        self.cache: dict[tuple[str, str], tuple[int, np.ndarray]] = {}

    def series(self, instrument: str, field: str) -> tuple[int, np.ndarray] | None:
        key = (instrument, field)
        if key in self.cache:
            return self.cache[key]
        path = self.feature_root / instrument.lower() / f"{field}.day.bin"
        if not path.exists():
            return None
        raw = np.fromfile(path, dtype="<f4")
        if len(raw) < 2 or not np.isfinite(raw[0]):
            return None
        value = (int(raw[0]), raw[1:])
        self.cache[key] = value
        return value

    def window(self, instrument: str, field: str, start: int, end: int) -> np.ndarray:
        result = np.full(end - start + 1, np.nan, dtype=float)
        stored = self.series(instrument, field)
        if stored is None:
            return result
        first, values = stored
        source_start = max(start, first)
        source_end = min(end, first + len(values) - 1)
        if source_start <= source_end:
            result[source_start - start : source_end - start + 1] = values[
                source_start - first : source_end - first + 1
            ]
        return result


def point_in_time_members(market: str, dates: list[pd.Timestamp]) -> dict[pd.Timestamp, set[str]]:
    path = QLIB_DATA_DIR / "instruments" / f"{market}.txt"
    if not path.exists():
        raise FileNotFoundError(path)
    wanted = [(date.strftime("%Y-%m-%d"), date) for date in dates]
    result = {date: set() for date in dates}
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            parts = line.rstrip().split("\t")
            if len(parts) < 3:
                continue
            instrument, start, end = parts[:3]
            for text, date in wanted:
                if start <= text <= end:
                    result[date].add(instrument)
    return result


def _value(values: np.ndarray, offset: int) -> float:
    return float(values[offset]) if 0 <= offset < len(values) else np.nan


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
            # One shared [T-252, T+22] coordinate system makes offsets auditable.
            start, end = t - 252, t + 22
            close = store.window(instrument, "close", start, end)
            open_ = store.window(instrument, "open", start, end)
            high = store.window(instrument, "high", start, end)
            low = store.window(instrument, "low", start, end)
            volume = store.window(instrument, "volume", start, end)
            amount = store.window(instrument, "amount", start, end)
            now = 252
            daily = close[now - 59 : now + 1] / close[now - 60 : now] - 1.0
            amount_window = amount[now - 19 : now + 1]
            mean_amount = (
                float(np.nanmean(amount_window))
                if np.isfinite(amount_window).any()
                else np.nan
            )
            records.append(
                {
                    "instrument": instrument,
                    "datetime": date,
                    "ret_5": _value(close, now) / _value(close, now - 5) - 1.0,
                    "ret_20": _value(close, now) / _value(close, now - 20) - 1.0,
                    "mom_6_1": _value(close, now - 21) / _value(close, now - 126) - 1.0,
                    "mom_12_1": _value(close, now - 21) / _value(close, now - 252) - 1.0,
                    "vol_60": float(np.nanstd(daily, ddof=0)) if np.isfinite(daily).sum() >= 50 else np.nan,
                    "amount_20": mean_amount,
                    "close": _value(close, now),
                    "forward_21": _value(open_, now + 22) / _value(open_, now + 1) - 1.0,
                    "entry_open": _value(open_, now + 1),
                    "entry_high": _value(high, now + 1),
                    "entry_low": _value(low, now + 1),
                    "entry_volume": _value(volume, now + 1),
                }
            )
    frame = pd.DataFrame(records)
    return frame.set_index(["instrument", "datetime"]).sort_index()


def _percentile_rank(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    return series.rank(pct=True, ascending=higher_is_better)


def prepare_snapshot(snapshot: pd.DataFrame, config: Config) -> pd.DataFrame:
    frame = snapshot.replace([np.inf, -np.inf], np.nan).copy()
    required = ["mom_12_1", "mom_6_1", "ret_20", "vol_60", "amount_20", "close"]
    frame = frame.dropna(subset=required)
    if frame.empty:
        return frame

    liquidity_floor = frame["amount_20"].quantile(config.liquidity_quantile)
    frame = frame.loc[
        (frame["amount_20"] >= liquidity_floor)
        & (frame["close"] >= config.min_price)
        & frame["forward_21"].notna()
        & frame["entry_open"].notna()
        & (frame["entry_volume"].fillna(0) > 0)
    ].copy()

    # If next day's open equals the entire daily range and gaps >9.5%, a main-board
    # A-share buy is generally not executable.  This conservative proxy may reject
    # some ChiNext/STAR entries whose applicable limit is wider.
    locked_up = (
        np.isclose(frame["entry_open"], frame["entry_high"], rtol=1e-5, atol=1e-8)
        & np.isclose(frame["entry_open"], frame["entry_low"], rtol=1e-5, atol=1e-8)
        & (frame["entry_open"] / frame["close"] - 1 >= 0.095)
    )
    frame = frame.loc[~locked_up].copy()
    if frame.empty:
        return frame

    frame["score_momentum_12_1"] = _percentile_rank(frame["mom_12_1"])
    frame["score_momentum_6_1"] = _percentile_rank(frame["mom_6_1"])
    frame["score_short_reversal"] = _percentile_rank(frame["ret_20"], False)
    frame["score_low_volatility"] = _percentile_rank(frame["vol_60"], False)
    frame["score_high_volatility"] = _percentile_rank(frame["vol_60"])
    frame["score_lowvol_momentum"] = (
        0.50 * frame["score_low_volatility"]
        + 0.25 * frame["score_momentum_6_1"]
        + 0.25 * frame["score_momentum_12_1"]
    )
    return frame


def select_portfolios(frame: pd.DataFrame, top_n: int) -> dict[str, list[str]]:
    strategies = {
        "momentum_12_1": "score_momentum_12_1",
        "momentum_6_1": "score_momentum_6_1",
        "short_reversal": "score_short_reversal",
        "low_volatility": "score_low_volatility",
        "lowvol_momentum": "score_lowvol_momentum",
        # Negative control: the opposite side of the low-volatility hypothesis.
        "high_volatility": "score_high_volatility",
    }
    selected = {
        name: frame.nlargest(min(top_n, len(frame)), score).index.tolist()
        for name, score in strategies.items()
    }
    selected["eligible_equal_weight"] = frame.index.tolist()
    return selected


def run_periods(panel: pd.DataFrame, dates: list[pd.Timestamp], config: Config) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    previous: dict[str, set[str]] = {}

    for number, date in enumerate(dates):
        try:
            snapshot = panel.xs(date, level="datetime")
        except KeyError:
            continue
        frame = prepare_snapshot(snapshot, config)
        if len(frame) < config.top_n:
            continue
        portfolios = select_portfolios(frame, config.top_n)

        for strategy, instruments in portfolios.items():
            current = set(instruments)
            old = previous.get(strategy, set())
            denominator = max(len(current), 1)
            buy_turnover = len(current - old) / denominator
            sell_turnover = len(old - current) / max(len(old), 1)
            cost = buy_turnover * config.open_cost + sell_turnover * config.close_cost
            gross = float(frame.loc[instruments, "forward_21"].mean())
            net = (1.0 + gross) * (1.0 - cost) - 1.0
            records.append(
                {
                    "signal_date": date,
                    "period": number,
                    "strategy": strategy,
                    "n_holdings": len(instruments),
                    "universe_size": len(frame),
                    "gross_return": gross,
                    "cost": cost,
                    "net_return": net,
                    "buy_turnover": buy_turnover,
                    "sell_turnover": sell_turnover,
                }
            )
            previous[strategy] = current

    result = pd.DataFrame(records)
    if result.empty:
        raise ValueError("Backtest produced no periods")

    # Include the cost of liquidating the final portfolio.
    last_indices = result.groupby("strategy")["signal_date"].idxmax()
    result.loc[last_indices, "cost"] += config.close_cost
    result.loc[last_indices, "net_return"] = (
        (1.0 + result.loc[last_indices, "gross_return"])
        * (1.0 - result.loc[last_indices, "cost"])
        - 1.0
    )
    return result.sort_values(["signal_date", "strategy"]).reset_index(drop=True)


def _max_drawdown(returns: pd.Series) -> float:
    wealth = (1.0 + returns).cumprod()
    return float((wealth / wealth.cummax() - 1.0).min())


def _bootstrap_mean_ci(values: np.ndarray, rng: np.random.Generator, samples: int) -> tuple[float, float]:
    if len(values) < 2:
        return np.nan, np.nan
    # Chunking keeps memory bounded for long experiments.
    means: list[np.ndarray] = []
    remaining = samples
    while remaining:
        count = min(remaining, 1000)
        indices = rng.integers(0, len(values), size=(count, len(values)))
        means.append(values[indices].mean(axis=1))
        remaining -= count
    distribution = np.concatenate(means)
    low, high = np.quantile(distribution, [0.025, 0.975])
    return float(low), float(high)


def summarize(periods: pd.DataFrame, config: Config) -> pd.DataFrame:
    periods_per_year = 252 / config.holding_days
    pivot = periods.pivot(index="signal_date", columns="strategy", values="net_return")
    benchmark = pivot["eligible_equal_weight"]
    rng = np.random.default_rng(config.seed)
    rows: list[dict[str, Any]] = []

    for strategy in sorted(pivot.columns):
        returns = pivot[strategy].dropna()
        aligned = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
        excess = (aligned.iloc[:, 0] - aligned.iloc[:, 1]).to_numpy()
        std = float(returns.std(ddof=1))
        annual_return = float((1.0 + returns).prod() ** (periods_per_year / len(returns)) - 1.0)
        annual_vol = std * np.sqrt(periods_per_year)
        ci_low, ci_high = _bootstrap_mean_ci(excess, rng, config.bootstrap_samples)
        rows.append(
            {
                "strategy": strategy,
                "periods": len(returns),
                "annual_return_net": annual_return,
                "annual_volatility": annual_vol,
                "sharpe_zero_rf": annual_return / annual_vol if annual_vol > 0 else np.nan,
                "endpoint_max_drawdown": _max_drawdown(returns),
                "win_rate": float((returns > 0).mean()),
                "mean_period_excess": float(np.mean(excess)),
                "excess_win_rate": float(np.mean(excess > 0)),
                "excess_mean_ci_2_5": ci_low,
                "excess_mean_ci_97_5": ci_high,
                "mean_one_way_turnover": float(
                    periods.loc[periods["strategy"] == strategy, ["buy_turnover", "sell_turnover"]]
                    .mean(axis=1)
                    .mean()
                ),
                "total_explicit_cost": float(periods.loc[periods["strategy"] == strategy, "cost"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("annual_return_net", ascending=False).reset_index(drop=True)


def subperiod_summary(periods: pd.DataFrame) -> pd.DataFrame:
    bins = [
        ("2008-2014", "2008-01-01", "2014-12-31"),
        ("2015-2019", "2015-01-01", "2019-12-31"),
        ("2020-2026", "2020-01-01", "2026-12-31"),
    ]
    rows: list[dict[str, Any]] = []
    for label, start, end in bins:
        part = periods.loc[periods["signal_date"].between(start, end)]
        for strategy, group in part.groupby("strategy"):
            returns = group.sort_values("signal_date")["net_return"]
            if returns.empty:
                continue
            annual = float((1 + returns).prod() ** (12 / len(returns)) - 1)
            rows.append(
                {
                    "subperiod": label,
                    "strategy": strategy,
                    "periods": len(returns),
                    "annual_return_net": annual,
                    "endpoint_max_drawdown": _max_drawdown(returns),
                }
            )
    return pd.DataFrame(rows)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transfer-test classic factors on A-shares")
    parser.add_argument("--start", default=Config.start)
    parser.add_argument("--end", default=Config.end)
    parser.add_argument("--market", default=Config.market)
    parser.add_argument("--top-n", type=int, default=Config.top_n)
    parser.add_argument("--bootstrap-samples", type=int, default=Config.bootstrap_samples)
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    config = Config(
        market=args.market,
        start=args.start,
        end=args.end,
        top_n=args.top_n,
        bootstrap_samples=args.bootstrap_samples,
    )
    dates = signal_dates(calendar(), config)
    print(f"Loading {config.market}: {dates[0].date()} to {dates[-1].date()} ({len(dates)} signals)")
    panel = load_panel(config, dates)
    print(f"Signal rows loaded: {len(panel):,}")
    periods = run_periods(panel, dates, config)
    summary = summarize(periods, config)
    subs = subperiod_summary(periods)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = OUTPUT_DIR / "factor_transfer" / stamp
    root.mkdir(parents=True, exist_ok=True)
    periods.to_csv(root / "period_returns.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(root / "summary.csv", index=False, encoding="utf-8-sig")
    subs.to_csv(root / "subperiods.csv", index=False, encoding="utf-8-sig")
    payload = {
        "run": stamp,
        "config": asdict(config),
        "method": {
            "universe": "point-in-time CSI 800 membership from local Qlib instrument intervals",
            "signal_and_execution": "T close signal; T+1 open buy; T+22 open sell; non-overlapping 21-session periods",
            "filters": "252-session history, bottom 20% liquidity removed, price >= 2, suspended and one-price limit-up entries removed",
            "costs": "0.03% buys and 0.13% sells, multiplied by realized turnover",
            "warning": "endpoint drawdown only; no locked-limit/delisting exit state machine",
        },
        "summary": summary.to_dict(orient="records"),
        "subperiods": subs.to_dict(orient="records"),
    }
    payload = _json_safe(payload)
    (root / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "factor_transfer_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print(f"Saved to {root}")
    return payload


if __name__ == "__main__":
    main()
