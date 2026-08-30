"""养家情绪周期轮动回测 — Yangjia Sentiment Cycle Rotation Backtest

基于"炒股养家"(林广昌)交易哲学的量化策略回测。

核心理念量化映射：
1. 情绪周期判断 → 市场涨跌家数比、强弱股占比、赚钱效应指标
2. 买在分歧，卖在一致 → 龙头首阴(回调放量)信号加分
3. 强势做龙头 → 动量+放量+趋势确认 多因子排序
4. 弱势做超跌 → 超跌深度+量能恢复+流动性质量 排序
5. 动态仓位管理 → 情绪得分映射至仓位比例

策略对比：
  yangjia_leader        — 纯动量龙头策略(强势期逻辑)
  yangjia_oversold      — 纯超跌反弹策略(弱势期逻辑)
  yangjia_adaptive      — 情绪自适应切换(强→龙头, 弱→超跌)
  yangjia_adaptive_sized — 自适应 + 仓位管理(完整养家策略)
  eligible_equal_weight  — 全域等权基准

信号: T日收盘 → T+1日开盘买入 → 持有N个交易日 → 卖出
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
    _json_safe,
    _max_drawdown,
    calendar,
    point_in_time_members,
)

REGIME_STRONG = "strong"
REGIME_WEAK = "weak"
REGIME_NEUTRAL = "neutral"

STRATEGIES = [
    "pure_reversal",
    "yangjia_leader",
    "yangjia_oversold",
    "yangjia_adaptive",
    "yangjia_adaptive_sized",
    "eligible_equal_weight",
]


@dataclass(frozen=True)
class Config:
    market: str = "csi800"
    start: str = "2015-01-05"
    end: str = "2026-05-29"
    holding_days: int = 5
    top_n: int = 30
    liquidity_quantile: float = 0.20
    min_price: float = 2.0
    open_cost: float = 0.0003
    close_cost: float = 0.0013
    strong_threshold: float = 0.55
    weak_threshold: float = 0.42
    strong_exposure: float = 1.0
    neutral_exposure: float = 0.8
    weak_exposure: float = 0.15
    seed: int = 20260823
    bootstrap_samples: int = 5000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signal_dates(cal: pd.DatetimeIndex, config: Config) -> list[pd.Timestamp]:
    first = int(cal.searchsorted(pd.Timestamp(config.start), side="left"))
    last_req = int(cal.searchsorted(pd.Timestamp(config.end), side="right")) - 1
    last = min(last_req, len(cal) - config.holding_days - 2)
    if first > last:
        raise ValueError("No test dates remain after reserving the forward window")
    return [pd.Timestamp(cal[i]) for i in range(first, last + 1, config.holding_days)]


def _fr(new: float, old: float) -> float:
    if not np.isfinite(new) or not np.isfinite(old) or old <= 0:
        return np.nan
    return float(new / old - 1.0)


def _smean(arr: np.ndarray) -> float:
    c = arr[np.isfinite(arr)]
    return float(c.mean()) if len(c) > 0 else np.nan


def _rank(s: pd.Series, ascending: bool = True) -> pd.Series:
    return s.rank(pct=True, ascending=ascending).fillna(0.5)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_panel(config: Config, dates: list[pd.Timestamp]) -> pd.DataFrame:
    cal = calendar()
    positions = {d: int(cal.searchsorted(d)) for d in dates}
    memberships = point_in_time_members(config.market, dates)
    store = RawQlibStore()
    records: list[dict[str, Any]] = []
    lookback = 60
    fwd = config.holding_days + 2

    for num, date in enumerate(dates, 1):
        t = positions[date]
        members = memberships[date]
        if num == 1 or num % 50 == 0 or num == len(dates):
            print(
                f"  [{num}/{len(dates)}] {date.date()} ({len(members)} members)",
                flush=True,
            )
        for inst in members:
            s, e = t - lookback, t + fwd
            c = store.window(inst, "close", s, e)
            o = store.window(inst, "open", s, e)
            h = store.window(inst, "high", s, e)
            lo = store.window(inst, "low", s, e)
            v = store.window(inst, "volume", s, e)
            a = store.window(inst, "amount", s, e)
            n = lookback  # index of T in arrays

            ret_1 = _fr(c[n], c[n - 1])
            ret_3 = _fr(c[n], c[n - 3])
            ret_5 = _fr(c[n], c[n - 5])
            ret_10 = _fr(c[n], c[n - 10])
            ret_20 = _fr(c[n], c[n - 20])

            amt_5 = _smean(a[n - 4 : n + 1])
            amt_20 = _smean(a[n - 19 : n + 1])
            amt_prior = _smean(a[n - 39 : n - 19])
            vol_bkout = (
                _fr(amt_5, amt_prior)
                if np.isfinite(amt_5) and np.isfinite(amt_prior) and amt_prior > 0
                else np.nan
            )

            ma20 = _smean(c[n - 19 : n + 1])
            trend_20 = (
                _fr(float(c[n]), ma20) if np.isfinite(ma20) and ma20 > 0 else np.nan
            )

            eo = float(o[n + 1])
            eh = float(h[n + 1])
            el = float(lo[n + 1])
            ev = float(v[n + 1])
            exit_idx = n + config.holding_days + 1
            fwd_ret = (
                _fr(float(o[exit_idx]), eo) if exit_idx < len(o) else np.nan
            )

            records.append(
                {
                    "instrument": inst,
                    "datetime": date,
                    "ret_1": ret_1,
                    "ret_3": ret_3,
                    "ret_5": ret_5,
                    "ret_10": ret_10,
                    "ret_20": ret_20,
                    "amount_20": amt_20,
                    "volume_breakout": vol_bkout,
                    "trend_20": trend_20,
                    "close": float(c[n]),
                    "entry_open": eo,
                    "entry_high": eh,
                    "entry_low": el,
                    "entry_volume": ev,
                    "forward": fwd_ret,
                }
            )

    return pd.DataFrame(records).set_index(["instrument", "datetime"]).sort_index()


# ---------------------------------------------------------------------------
# Sentiment & regime
# ---------------------------------------------------------------------------

def compute_sentiment(snapshot: pd.DataFrame) -> dict[str, float]:
    """Market-wide sentiment from the full CSI-800 cross-section at T.

    Uses 4 dimensions:
      breadth     — 涨跌比(当日涨的比例)
      sw_ratio    — 强弱股比(5日涨>5% vs 跌>5%)
      money_effect — 赚钱效应(5日均收益率)
      trend_20    — 中期趋势(20日均收益率, 检测持续性下跌)
    """
    ret1 = snapshot["ret_1"].dropna()
    ret5 = snapshot["ret_5"].dropna()
    ret20 = snapshot["ret_20"].dropna()

    advance_ratio = float((ret1 > 0).mean()) if len(ret1) > 0 else 0.5
    strong_ratio = float((ret5 > 0.05).mean()) if len(ret5) > 0 else 0.0
    weak_ratio = float((ret5 < -0.05).mean()) if len(ret5) > 0 else 0.0
    limit_up_proxy = float((ret1 > 0.095).mean()) if len(ret1) > 0 else 0.0
    limit_down_proxy = float((ret1 < -0.095).mean()) if len(ret1) > 0 else 0.0
    avg_ret5 = float(ret5.mean()) if len(ret5) > 0 else 0.0
    avg_ret20 = float(ret20.median()) if len(ret20) > 0 else 0.0

    sw_ratio = strong_ratio / max(strong_ratio + weak_ratio, 0.01)
    money_effect = float(np.clip(avg_ret5 * 10 + 0.5, 0, 1))
    breadth = float(np.clip(advance_ratio, 0, 1))
    trend_indicator = float(np.clip(avg_ret20 * 5 + 0.5, 0, 1))

    score = (
        0.25 * breadth
        + 0.20 * sw_ratio
        + 0.25 * money_effect
        + 0.30 * trend_indicator
    )

    return {
        "sentiment_score": score,
        "advance_ratio": advance_ratio,
        "strong_ratio": strong_ratio,
        "weak_ratio": weak_ratio,
        "limit_up_proxy": limit_up_proxy,
        "limit_down_proxy": limit_down_proxy,
        "avg_ret5": avg_ret5,
        "avg_ret20": avg_ret20,
    }


def classify_regime(score: float, config: Config) -> str:
    if score >= config.strong_threshold:
        return REGIME_STRONG
    if score <= config.weak_threshold:
        return REGIME_WEAK
    return REGIME_NEUTRAL


def get_exposure(score: float, config: Config) -> float:
    regime = classify_regime(score, config)
    if regime == REGIME_STRONG:
        return config.strong_exposure
    if regime == REGIME_WEAK:
        return config.weak_exposure
    return config.neutral_exposure


# ---------------------------------------------------------------------------
# Tradability filter
# ---------------------------------------------------------------------------

def prepare_snapshot(snapshot: pd.DataFrame, config: Config) -> pd.DataFrame:
    frame = snapshot.replace([np.inf, -np.inf], np.nan).copy()
    required = [
        "ret_5", "ret_10", "amount_20", "volume_breakout",
        "close", "entry_open", "entry_volume", "forward",
    ]
    frame = frame.dropna(subset=required)
    if frame.empty:
        return frame

    liq_floor = frame["amount_20"].quantile(config.liquidity_quantile)
    frame = frame.loc[
        (frame["amount_20"] >= liq_floor)
        & (frame["close"] >= config.min_price)
        & (frame["entry_volume"] > 0)
    ].copy()
    if frame.empty:
        return frame

    locked = (
        np.isclose(frame["entry_open"], frame["entry_high"], rtol=1e-5, atol=1e-8)
        & np.isclose(frame["entry_open"], frame["entry_low"], rtol=1e-5, atol=1e-8)
        & (frame["entry_open"] / frame["close"] - 1 >= 0.095)
    )
    return frame.loc[~locked].copy()


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_pure_reversal(frame: pd.DataFrame) -> pd.Series:
    """纯短期反转: 买入5日跌幅最大的股票。A股最强单因子基线。"""
    return _rank(frame["ret_5"], ascending=False)


def score_leader(frame: pd.DataFrame) -> pd.Series:
    """强势期评分: 买在分歧 — 中期趋势向上 + 短期回调 + 放量确认

    养家核心: 在上升趋势中的分歧/回调时买入,
    而非追涨(纯动量在A股短期均值回归下会亏损)。
    """
    base = (
        0.40 * _rank(frame["ret_5"], ascending=False)   # 短期回调(分歧信号)
        + 0.35 * _rank(frame["trend_20"])                # 中期趋势向上
        + 0.25 * _rank(frame["volume_breakout"])          # 放量(有分歧/有人气)
    )
    # 龙头首阴: 20日强势 + 当日回调 + 放量 = "买在分歧"经典信号
    dip = (
        (frame["ret_20"] > 0.05)
        & (frame["ret_1"] < 0)
        & (frame["volume_breakout"] > 0.1)
    )
    return base + 0.15 * dip.astype(float)


def score_oversold(frame: pd.DataFrame) -> pd.Series:
    """弱势期评分: 超跌反弹 — 跌幅深 + 早期反弹 + 量能恢复"""
    return (
        0.40 * _rank(frame["ret_20"], ascending=False)  # 20日超跌深度
        + 0.30 * _rank(frame["ret_1"])                   # 早期反弹信号
        + 0.30 * _rank(frame["volume_breakout"])          # 量能恢复
    )


def score_adaptive(frame: pd.DataFrame, regime: str) -> pd.Series:
    leader = score_leader(frame)
    reversal = score_pure_reversal(frame)
    if regime == REGIME_STRONG:
        return leader
    if regime == REGIME_WEAK:
        return reversal
    return 0.5 * _rank(leader) + 0.5 * _rank(reversal)


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def run_periods(
    panel: pd.DataFrame,
    dates: list[pd.Timestamp],
    config: Config,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    previous: dict[str, set[str]] = {s: set() for s in STRATEGIES}
    period_rows: list[dict[str, Any]] = []
    sentiment_rows: list[dict[str, Any]] = []

    for period, date in enumerate(dates):
        try:
            snapshot = panel.xs(date, level="datetime")
        except KeyError:
            continue

        sentiment = compute_sentiment(snapshot)
        regime = classify_regime(sentiment["sentiment_score"], config)
        exposure = get_exposure(sentiment["sentiment_score"], config)
        sentiment_rows.append(
            {"signal_date": date, "regime": regime, "exposure": exposure, **sentiment}
        )

        frame = prepare_snapshot(snapshot, config)
        if len(frame) < config.top_n:
            continue

        reversal_scores = score_pure_reversal(frame)
        leader_scores = score_leader(frame)
        oversold_scores = score_oversold(frame)
        adaptive_scores = score_adaptive(frame, regime)

        portfolios: dict[str, list[str]] = {
            "pure_reversal": reversal_scores.nlargest(config.top_n).index.tolist(),
            "yangjia_leader": leader_scores.nlargest(config.top_n).index.tolist(),
            "yangjia_oversold": oversold_scores.nlargest(config.top_n).index.tolist(),
            "yangjia_adaptive": adaptive_scores.nlargest(config.top_n).index.tolist(),
            "yangjia_adaptive_sized": adaptive_scores.nlargest(config.top_n).index.tolist(),
            "eligible_equal_weight": frame.index.tolist(),
        }

        for strategy, instruments in portfolios.items():
            current = set(instruments)
            old = previous[strategy]
            denom = max(len(current), 1)
            buy_to = len(current - old) / denom
            sell_to = len(old - current) / max(len(old), 1)
            cost = buy_to * config.open_cost + sell_to * config.close_cost

            realized = frame.loc[instruments, "forward"]
            missing = int(realized.isna().sum())
            gross = float(realized.fillna(-1.0).mean())

            if strategy == "yangjia_adaptive_sized":
                gross *= exposure
                cost *= exposure

            net = (1.0 + gross) * (1.0 - cost) - 1.0

            period_rows.append(
                {
                    "signal_date": date,
                    "period": period,
                    "strategy": strategy,
                    "regime": regime,
                    "sentiment": sentiment["sentiment_score"],
                    "exposure": exposure if strategy == "yangjia_adaptive_sized" else 1.0,
                    "n_holdings": len(instruments),
                    "universe_size": len(frame),
                    "gross_return": gross,
                    "cost": cost,
                    "net_return": net,
                    "buy_turnover": buy_to,
                    "sell_turnover": sell_to,
                    "missing_returns": missing,
                }
            )
            previous[strategy] = current

    periods = (
        pd.DataFrame(period_rows)
        .sort_values(["signal_date", "strategy"])
        .reset_index(drop=True)
    )
    sentiments = pd.DataFrame(sentiment_rows)
    if periods.empty:
        raise ValueError("Backtest produced no periods")
    return periods, sentiments


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarize(periods: pd.DataFrame, config: Config) -> pd.DataFrame:
    periods_per_year = 252 / config.holding_days
    pivot = periods.pivot(index="signal_date", columns="strategy", values="net_return")
    benchmark = pivot["eligible_equal_weight"]
    rng = np.random.default_rng(config.seed)
    rows: list[dict[str, Any]] = []

    for strategy in sorted(pivot.columns):
        rets = pivot[strategy].dropna()
        aligned = pd.concat([rets, benchmark], axis=1, join="inner").dropna()
        excess = (aligned.iloc[:, 0] - aligned.iloc[:, 1]).to_numpy()

        annual_ret = float(
            (1.0 + rets).prod() ** (periods_per_year / len(rets)) - 1.0
        )
        annual_vol = float(rets.std(ddof=1) * np.sqrt(periods_per_year))
        sharpe = annual_ret / annual_vol if annual_vol > 0 else np.nan
        mdd = _max_drawdown(rets)
        calmar = annual_ret / abs(mdd) if mdd < 0 else np.nan
        ci_lo, ci_hi = _bootstrap_mean_ci(excess, rng, config.bootstrap_samples)

        sp = periods[periods["strategy"] == strategy]
        rows.append(
            {
                "strategy": strategy,
                "periods": len(rets),
                "annual_return": annual_ret,
                "annual_volatility": annual_vol,
                "sharpe": sharpe,
                "max_drawdown": mdd,
                "calmar": calmar,
                "win_rate": float((rets > 0).mean()),
                "mean_excess": float(np.mean(excess)),
                "excess_win_rate": float(np.mean(excess > 0)),
                "excess_ci_2.5": ci_lo,
                "excess_ci_97.5": ci_hi,
                "avg_exposure": float(sp["exposure"].mean()),
                "mean_turnover": float(
                    sp[["buy_turnover", "sell_turnover"]].mean(axis=1).mean()
                ),
                "total_cost": float(sp["cost"].sum()),
            }
        )

    return (
        pd.DataFrame(rows)
        .sort_values("annual_return", ascending=False)
        .reset_index(drop=True)
    )


def subperiod_summary(periods: pd.DataFrame, config: Config) -> pd.DataFrame:
    bins = [
        ("2015-2017", "2015-01-01", "2017-12-31"),
        ("2018-2020", "2018-01-01", "2020-12-31"),
        ("2021-2023", "2021-01-01", "2023-12-31"),
        ("2024-2026", "2024-01-01", "2026-12-31"),
    ]
    ppy = 252 / config.holding_days
    rows: list[dict[str, Any]] = []
    for label, start, end in bins:
        part = periods.loc[periods["signal_date"].between(start, end)]
        if part.empty:
            continue
        for strategy, grp in part.groupby("strategy"):
            rets = grp.sort_values("signal_date")["net_return"]
            if rets.empty:
                continue
            annual = float((1 + rets).prod() ** (ppy / len(rets)) - 1)
            rows.append(
                {
                    "subperiod": label,
                    "strategy": strategy,
                    "periods": len(rets),
                    "annual_return": annual,
                    "max_drawdown": _max_drawdown(rets),
                    "win_rate": float((rets > 0).mean()),
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# CLI & main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="养家情绪周期轮动回测")
    p.add_argument("--start", default=Config.start)
    p.add_argument("--end", default=Config.end)
    p.add_argument("--market", default=Config.market)
    p.add_argument("--holding-days", type=int, default=Config.holding_days)
    p.add_argument("--top-n", type=int, default=Config.top_n)
    p.add_argument("--bootstrap-samples", type=int, default=Config.bootstrap_samples)
    return p.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    config = Config(
        market=args.market,
        start=args.start,
        end=args.end,
        holding_days=args.holding_days,
        top_n=args.top_n,
        bootstrap_samples=args.bootstrap_samples,
    )

    cal = calendar()
    dates = _signal_dates(cal, config)
    print("=" * 60)
    print("  养家情绪周期轮动回测  Yangjia Sentiment Cycle Backtest")
    print("=" * 60)
    print(f"  Market : {config.market.upper()}")
    print(f"  Period : {dates[0].date()} → {dates[-1].date()}")
    print(f"  Signals: {len(dates)} ({config.holding_days}-day intervals)")
    print(f"  Top-N  : {config.top_n}")
    print(f"  Costs  : open {config.open_cost:.4f} / close {config.close_cost:.4f}")
    print()

    print("Loading panel data …", flush=True)
    panel = load_panel(config, dates)
    print(f"Panel loaded: {len(panel):,} rows\n")

    print("Running backtest …", flush=True)
    periods, sentiments = run_periods(panel, dates, config)
    summary = summarize(periods, config)
    subs = subperiod_summary(periods, config)

    regime_dist = sentiments["regime"].value_counts()
    print()
    print("=" * 60)
    print("  Market Regime Distribution")
    print("-" * 60)
    for regime in [REGIME_STRONG, REGIME_NEUTRAL, REGIME_WEAK]:
        cnt = regime_dist.get(regime, 0)
        pct = cnt / len(sentiments) * 100
        label = {"strong": "强势期", "neutral": "中性期", "weak": "弱势期"}[regime]
        print(f"  {label} ({regime:>7s}): {cnt:>4d} periods  ({pct:5.1f}%)")

    print()
    print("=" * 60)
    print(f"  Strategy Performance Summary  ({config.holding_days}-day holding)")
    print("-" * 60)
    display = [
        "strategy",
        "annual_return",
        "annual_volatility",
        "sharpe",
        "max_drawdown",
        "calmar",
        "win_rate",
        "avg_exposure",
    ]
    print(summary[display].to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print()
    print("=" * 60)
    print("  Sub-period Annual Returns")
    print("-" * 60)
    if not subs.empty:
        sub_pivot = subs.pivot(
            index="strategy", columns="subperiod", values="annual_return"
        )
        print(sub_pivot.to_string(float_format=lambda x: f"{x:.4f}"))

    # Persist
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUTPUT_DIR / "yangjia_sentiment" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    periods.to_csv(out_dir / "period_returns.csv", index=False, encoding="utf-8-sig")
    sentiments.to_csv(
        out_dir / "sentiment_history.csv", index=False, encoding="utf-8-sig"
    )
    summary.to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig")
    subs.to_csv(out_dir / "subperiods.csv", index=False, encoding="utf-8-sig")

    payload: dict[str, Any] = {
        "run": stamp,
        "config": asdict(config),
        "method": {
            "philosophy": "基于炒股养家交易哲学: 情绪周期判断 + 买在分歧卖在一致 + 动态仓位",
            "universe": f"point-in-time {config.market.upper()} membership",
            "timing": (
                f"T close signal → T+1 open entry → "
                f"T+{config.holding_days + 1} open exit"
            ),
            "filters": (
                "60-session history; bottom 20% liquidity removed; "
                "price >= ¥2; one-price limit-up entries removed"
            ),
            "costs": f"open {config.open_cost:.4f} / close {config.close_cost:.4f}",
            "sentiment_inputs": [
                "advance_ratio (涨跌比)",
                "strong_ratio  (5日涨>5%占比)",
                "weak_ratio    (5日跌>5%占比)",
                "limit_up_proxy(涨停代理)",
                "avg_ret5      (5日均收益)",
            ],
            "strategies": {
                "yangjia_leader": "动量领涨(强势期逻辑，不切换)",
                "yangjia_oversold": "超跌反弹(弱势期逻辑，不切换)",
                "yangjia_adaptive": "情绪自适应切换(强→龙头, 弱→超跌, 中→均衡)",
                "yangjia_adaptive_sized": (
                    "自适应切换 + 仓位管理 "
                    f"(强{config.strong_exposure:.0%}/中{config.neutral_exposure:.0%}"
                    f"/弱{config.weak_exposure:.0%})"
                ),
                "eligible_equal_weight": "全域等权基准",
            },
        },
        "regime_distribution": {
            k: int(v) for k, v in regime_dist.items()
        },
        "summary": summary.to_dict("records"),
        "subperiods": subs.to_dict("records"),
    }
    safe = _json_safe(payload)
    result_path = out_dir / "results.json"
    result_path.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_path = OUTPUT_DIR / "yangjia_sentiment_latest.json"
    latest_path.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nResults saved → {out_dir}")
    return safe


if __name__ == "__main__":
    main()
