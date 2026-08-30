"""
可解释的 A 股基础候选生成器，并提供短周期历史截面回测。

定位：
- 不预测精确收益，不替代 UZI；
- 只负责从 CSI800 中找出“流动性足、趋势健康、不过热”的基础标的；
- 实时阶段再叠加公告、龙虎榜与 UZI 深度判断。

用法：
    .venv\\Scripts\\python.exe candidate_funnel.py scan
    .venv\\Scripts\\python.exe candidate_funnel.py backtest --samples 8
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import OUTPUT_DIR, QLIB_DATA_DIR


FIELDS = {
    "close": "$close",
    "ma20": "Mean($close,20)",
    "ma60": "Mean($close,60)",
    "ret5": "$close/Ref($close,5)-1",
    "ret20": "$close/Ref($close,20)-1",
    "ret60": "$close/Ref($close,60)-1",
    "vol20": "Std($close/Ref($close,1)-1,20)",
    "volume_ratio": "$volume/Mean($volume,20)",
    "liquidity20": "Mean($close*$volume,20)",
    "drawdown60": "$close/Max($high,60)-1",
    # T 日收盘筛选；T+1 开盘买入，T+6 开盘卖出。
    "forward_5d": "Ref($open,-6)/Ref($open,-1)-1",
}


@dataclass(frozen=True)
class FunnelConfig:
    market: str = "csi800"
    top_n: int = 30
    min_ret20: float = 0.02
    max_ret20: float = 0.30
    max_dist_ma20: float = 0.15
    min_drawdown60: float = -0.20
    min_volume_ratio: float = 0.50
    max_volume_ratio: float = 3.00
    liquidity_quantile: float = 0.30
    volatility_quantile: float = 0.80
    leader_share: float = 0.60


def init_qlib() -> None:
    import qlib
    from qlib.constant import REG_CN

    qlib.init(provider_uri=str(QLIB_DATA_DIR), region=REG_CN)


def get_calendar() -> pd.DatetimeIndex:
    from qlib.data import D

    return pd.DatetimeIndex(D.calendar(freq="day")).sort_values()


def load_factor_panel(market: str, start: str, end: str) -> pd.DataFrame:
    from qlib.data import D

    panel = D.features(
        D.instruments(market=market),
        list(FIELDS.values()),
        start_time=start,
        end_time=end,
        freq="day",
    )
    panel.columns = list(FIELDS)
    panel.index = panel.index.set_names(["instrument", "datetime"])
    return panel.sort_index()


def _rank(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    return series.rank(pct=True, ascending=higher_is_better)


def score_snapshot(snapshot: pd.DataFrame, config: FunnelConfig) -> pd.DataFrame:
    """仅使用当日及历史字段打分；forward_5d 仅保留用于回测评估。"""
    frame = snapshot.copy()
    numeric = list(FIELDS)
    frame[numeric] = frame[numeric].replace([np.inf, -np.inf], np.nan)

    frame["dist_ma20"] = frame["close"] / frame["ma20"] - 1
    frame["trend_ok"] = (
        (frame["close"] > frame["ma20"])
        & (frame["ma20"] > frame["ma60"])
        & frame["ret20"].between(config.min_ret20, config.max_ret20)
        & (frame["dist_ma20"] <= config.max_dist_ma20)
        & (frame["drawdown60"] >= config.min_drawdown60)
    )
    liquidity_floor = frame["liquidity20"].quantile(config.liquidity_quantile)
    volatility_ceiling = frame["vol20"].quantile(config.volatility_quantile)
    frame["eligible"] = (
        frame["trend_ok"]
        & (frame["liquidity20"] >= liquidity_floor)
        & (frame["vol20"] <= volatility_ceiling)
        & frame["volume_ratio"].between(
            config.min_volume_ratio, config.max_volume_ratio
        )
    )
    frame["leader_eligible"] = (
        (frame["close"] > frame["ma20"])
        & (frame["ret20"] > 0)
        & (frame["ret20"] <= 0.45)
        & (frame["dist_ma20"] <= 0.25)
        & (frame["drawdown60"] >= -0.25)
        & (frame["liquidity20"] >= liquidity_floor)
        & (frame["vol20"] <= frame["vol20"].quantile(0.90))
        & frame["volume_ratio"].between(0.40, 4.00)
    )

    # 每个分量均压缩到 [0, 1]，避免量纲和极端值主导。
    frame["rank_ret20"] = frame["ret20"].rank(pct=True)
    frame["rank_ret60"] = frame["ret60"].rank(pct=True)
    frame["rank_low_vol"] = frame["vol20"].rank(pct=True, ascending=False)
    frame["rank_liquidity"] = frame["liquidity20"].rank(pct=True)
    frame["rank_drawdown"] = frame["drawdown60"].rank(pct=True)
    frame["volume_quality"] = (
        1 - np.log(frame["volume_ratio"].clip(0.20, 5.0)).abs() / np.log(5.0)
    ).clip(0, 1)

    frame["score"] = (
        0.25 * frame["rank_ret20"]
        + 0.20 * frame["rank_ret60"]
        + 0.15 * frame["rank_low_vol"]
        + 0.15 * frame["rank_liquidity"]
        + 0.15 * frame["rank_drawdown"]
        + 0.10 * frame["volume_quality"]
    )
    # 过热股票即使仍满足硬过滤，也进行额外惩罚。
    frame["overheat_penalty"] = (
        (frame["ret5"] > 0.12).astype(float) * 0.10
        + (frame["dist_ma20"] > 0.12).astype(float) * 0.10
    )
    frame["score"] -= frame["overheat_penalty"]
    frame["leader_score"] = (
        0.45 * frame["rank_ret20"]
        + 0.25 * frame["rank_ret60"]
        + 0.10 * frame["rank_liquidity"]
        + 0.10 * frame["rank_drawdown"]
        + 0.10 * frame["volume_quality"]
        - 0.50 * frame["overheat_penalty"]
    )
    return frame


def select_from_scored(
    scored: pd.DataFrame, config: FunnelConfig
) -> pd.DataFrame:
    """趋势领涨池 + 稳健趋势池，去重后合并。"""
    leader_n = int(round(config.top_n * config.leader_share))
    steady_n = config.top_n - leader_n
    leaders = (
        scored.loc[scored["leader_eligible"]]
        .sort_values(["leader_score", "liquidity20"], ascending=False)
        .head(leader_n)
    )
    steady = (
        scored.loc[scored["eligible"] & ~scored.index.isin(leaders.index)]
        .sort_values(["score", "liquidity20"], ascending=False)
        .head(steady_n)
    )
    selected = pd.concat([leaders, steady])
    if len(selected) < config.top_n:
        fallback = (
            scored.loc[
                scored["leader_eligible"] & ~scored.index.isin(selected.index)
            ]
            .sort_values("leader_score", ascending=False)
            .head(config.top_n - len(selected))
        )
        selected = pd.concat([selected, fallback])
    selected = selected.copy()
    selected["pool"] = np.where(
        selected.index.isin(leaders.index), "leader", "steady"
    )
    selected.insert(0, "rank", range(1, len(selected) + 1))
    return selected


def select_candidates(
    panel: pd.DataFrame, date: pd.Timestamp, config: FunnelConfig
) -> pd.DataFrame:
    try:
        snapshot = panel.xs(date, level="datetime")
    except KeyError:
        return pd.DataFrame()
    scored = score_snapshot(snapshot, config)
    return select_from_scored(scored, config)


def choose_sample_dates(
    calendar: pd.DatetimeIndex,
    start: str,
    end: str,
    samples: int,
    forward_days: int = 6,
) -> list[pd.Timestamp]:
    start_idx = int(calendar.searchsorted(pd.Timestamp(start), side="left"))
    end_idx = int(calendar.searchsorted(pd.Timestamp(end), side="right")) - 1
    end_idx = min(end_idx, len(calendar) - forward_days - 1)
    available = calendar[start_idx : end_idx + 1]
    if len(available) < samples:
        return list(available)
    positions = np.linspace(0, len(available) - 1, samples, dtype=int)
    return [pd.Timestamp(available[pos]) for pos in sorted(set(positions))]


def _portfolio_stats(returns: list[float]) -> dict[str, float | int | None]:
    clean = pd.Series(returns, dtype=float).dropna()
    if clean.empty:
        return {"count": 0, "mean": None, "median": None, "win_rate": None}
    return {
        "count": int(len(clean)),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "win_rate": float((clean > 0).mean()),
        "worst": float(clean.min()),
        "best": float(clean.max()),
    }


def run_backtest(
    panel: pd.DataFrame,
    sample_dates: list[pd.Timestamp],
    config: FunnelConfig,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    candidate_returns: list[float] = []
    market_returns: list[float] = []
    momentum_returns: list[float] = []
    excess_returns: list[float] = []

    for date in sample_dates:
        snapshot = panel.xs(date, level="datetime")
        scored = score_snapshot(snapshot, config)
        selected = select_from_scored(scored, config)
        evaluable = selected["forward_5d"].dropna()

        market = scored["forward_5d"].dropna()
        liquid = scored.loc[
            scored["liquidity20"] >= scored["liquidity20"].quantile(
                config.liquidity_quantile
            )
        ]
        momentum = (
            liquid.sort_values("ret20", ascending=False)
            .head(config.top_n)["forward_5d"]
            .dropna()
        )

        candidate_ret = float(evaluable.mean()) if not evaluable.empty else np.nan
        market_ret = float(market.mean()) if not market.empty else np.nan
        momentum_ret = float(momentum.mean()) if not momentum.empty else np.nan
        excess = candidate_ret - market_ret

        candidate_returns.append(candidate_ret)
        market_returns.append(market_ret)
        momentum_returns.append(momentum_ret)
        excess_returns.append(excess)
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "eligible_count": int(scored["eligible"].sum()),
                "leader_eligible_count": int(scored["leader_eligible"].sum()),
                "selected_count": int(len(selected)),
                "leader_count": int((selected["pool"] == "leader").sum()),
                "candidate_5d": candidate_ret,
                "market_equal_weight_5d": market_ret,
                "momentum_top_5d": momentum_ret,
                "excess_vs_market": excess,
                "candidate_win_rate": (
                    float((evaluable > 0).mean()) if not evaluable.empty else np.nan
                ),
            }
        )

    return {
        "methodology": {
            "signal_time": "T close",
            "entry": "T+1 open",
            "exit": "T+6 open",
            "holding_days": 5,
            "market": config.market,
            "top_n": config.top_n,
            "selection": "60% trend leaders + 40% steady trend; liquidity and anti-overheat gates",
            "excluded_from_historical_test": [
                "UZI qualitative judgment",
                "current-only fundamentals",
                "announcement catalyst",
                "LHB seats",
            ],
        },
        "dates": rows,
        "summary": {
            "candidate": _portfolio_stats(candidate_returns),
            "market_equal_weight": _portfolio_stats(market_returns),
            "momentum_top": _portfolio_stats(momentum_returns),
            "excess_vs_market": _portfolio_stats(excess_returns),
        },
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def run_scan(config: FunnelConfig, date: str | None) -> dict[str, Any]:
    calendar = get_calendar()
    scan_date = (
        pd.Timestamp(date)
        if date
        else pd.Timestamp(calendar[-1])
    )
    start_idx = max(0, int(calendar.searchsorted(scan_date)) - 70)
    panel = load_factor_panel(
        config.market,
        calendar[start_idx].strftime("%Y-%m-%d"),
        scan_date.strftime("%Y-%m-%d"),
    )
    selected = select_candidates(panel, scan_date, config)
    records = []
    for instrument, row in selected.iterrows():
        records.append(
            {
                "rank": int(row["rank"]),
                "instrument": instrument,
                "score": round(float(row["score"]), 4),
                "leader_score": round(float(row["leader_score"]), 4),
                "pool": row["pool"],
                "ret20": round(float(row["ret20"]), 4),
                "ret60": round(float(row["ret60"]), 4),
                "vol20": round(float(row["vol20"]), 4),
                "dist_ma20": round(float(row["dist_ma20"]), 4),
                "volume_ratio": round(float(row["volume_ratio"]), 3),
                "drawdown60": round(float(row["drawdown60"]), 4),
            }
        )
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date": scan_date.strftime("%Y-%m-%d"),
        "market": config.market,
        "candidates": records,
    }
    path = OUTPUT_DIR / f"base_candidates_{scan_date.strftime('%Y%m%d')}.json"
    path.write_text(
        json.dumps(json_safe(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"{scan_date.date()} 候选 {len(records)} 只，结果: {path}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UZI 前置基础候选漏斗")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="生成指定日/最新日候选")
    scan.add_argument("--date")
    scan.add_argument("--top", type=int, default=30)
    scan.add_argument("--market", default="csi800")

    backtest = sub.add_parser("backtest", help="若干历史截面5日回测")
    backtest.add_argument("--start", default="2025-08-01")
    backtest.add_argument("--end", default="2026-06-15")
    backtest.add_argument("--samples", type=int, default=8)
    backtest.add_argument("--top", type=int, default=30)
    backtest.add_argument("--market", default="csi800")
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    init_qlib()
    config = FunnelConfig(market=args.market, top_n=args.top)
    if args.command == "scan":
        return run_scan(config, args.date)

    calendar = get_calendar()
    dates = choose_sample_dates(calendar, args.start, args.end, args.samples)
    load_start_idx = max(0, int(calendar.searchsorted(dates[0])) - 70)
    load_end_idx = min(
        len(calendar) - 1, int(calendar.searchsorted(dates[-1])) + 7
    )
    panel = load_factor_panel(
        config.market,
        calendar[load_start_idx].strftime("%Y-%m-%d"),
        calendar[load_end_idx].strftime("%Y-%m-%d"),
    )
    result = run_backtest(panel, dates, config)
    result["config"] = config.__dict__
    safe = json_safe(result)
    path = OUTPUT_DIR / "candidate_funnel_backtest.json"
    path.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = result["summary"]
    print(
        f"候选均值={summary['candidate']['mean']:.2%} | "
        f"市场均值={summary['market_equal_weight']['mean']:.2%} | "
        f"超额均值={summary['excess_vs_market']['mean']:.2%} | "
        f"超额胜率={summary['excess_vs_market']['win_rate']:.1%}"
    )
    print(f"结果: {path}")
    return safe


if __name__ == "__main__":
    main()
