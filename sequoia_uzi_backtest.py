"""Sequoia-X + UZI 的无未来数据历史截面试验。

Sequoia-X 上游目前只支持“以数据库最新一天运行”，本脚本逐字复现其六个
纯日线策略的条件，并允许把数据截断在任意历史交易日。UZI 本身没有 as-of
参数，所以这里只调用原版 UZI 的 K 线维度评分作为历史技术 gate；新闻、财报、
研报、资金流等当前数据一律不进入回测，避免时间穿越。

收益口径：T 日收盘出信号，T+1 开盘买入，持有 5/10/20 个交易日后开盘卖出。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import OUTPUT_DIR, QLIB_DATA_DIR, UZI_SCRIPTS_DIR


DEFAULT_DATES = [
    "2026-01-09",
    "2026-02-06",
    "2026-03-06",
    "2026-04-10",
    "2026-05-08",
    "2026-06-01",
]

STRATEGY_WEIGHTS = {
    "rps_breakout": 3,
    "high_tight_flag": 3,
    "turtle_trade": 2,
    "ma_volume": 2,
    "limit_up_shakeout": 1,
    "uptrend_limit_down": 1,
}


@dataclass(frozen=True)
class BacktestConfig:
    top_n: int = 10
    horizons: tuple[int, ...] = (5, 10, 20)
    uzi_min_score: int = 7
    round_trip_cost: float = 0.002
    include_uzi: bool = True


def init_qlib() -> None:
    import qlib
    from qlib.constant import REG_CN

    qlib.init(provider_uri=str(QLIB_DATA_DIR), region=REG_CN)


def load_panel(start: str, end: str) -> pd.DataFrame:
    from qlib.data import D

    fields = ["$open", "$high", "$low", "$close", "$volume"]
    panel = D.features(
        D.instruments(market="all"),
        fields,
        start_time=start,
        end_time=end,
        freq="day",
    )
    panel.columns = ["open", "high", "low", "close", "volume"]
    panel.index = panel.index.set_names(["instrument", "datetime"])
    # Sequoia-X 上游 DataEngine._to_baostock_code 只实现沪深映射；排除 BJ，
    # 避免 qlib 的北交所标的进入一个原生系统实际无法生成的历史候选池。
    instruments = panel.index.get_level_values("instrument").astype(str)
    panel = panel.loc[instruments.str.startswith(("SH", "SZ"))]
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(subset=["close"])
    return panel.sort_index()


def add_indicators(panel: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    """仅做按股票的后向指标；forward_* 字段只在最后评估时读取。"""
    parts: list[pd.DataFrame] = []
    for instrument, group in panel.groupby(level="instrument", sort=False):
        frame = group.droplevel("instrument").copy()
        frame["instrument"] = instrument

        frame["ma5"] = frame["close"].rolling(5).mean()
        frame["ma10"] = frame["close"].rolling(10).mean()
        frame["ma20"] = frame["close"].rolling(20).mean()
        frame["ma60"] = frame["close"].rolling(60).mean()
        frame["ma120"] = frame["close"].rolling(120).mean()
        frame["ma200"] = frame["close"].rolling(200).mean()
        frame["ma200_60ago"] = frame["ma200"].shift(60)
        frame["vol_ma20"] = frame["volume"].rolling(20).mean()
        frame["prev20_vol_mean"] = frame["volume"].shift(1).rolling(20).mean()
        frame["high20_prev"] = frame["high"].shift(1).rolling(20).max()
        frame["high40"] = frame["high"].rolling(40).max()
        frame["low40"] = frame["low"].rolling(40).min()
        frame["high10"] = frame["high"].rolling(10).max()
        frame["low10"] = frame["low"].rolling(10).min()
        frame["high120"] = frame["high"].rolling(120, min_periods=60).max()
        frame["ret120"] = frame["close"] / frame["close"].shift(120) - 1
        rolling_peak = frame["close"].rolling(252, min_periods=1).max()
        rolling_drawdown = frame["close"] / rolling_peak - 1
        frame["max_drawdown252"] = rolling_drawdown.rolling(252, min_periods=1).min()
        frame["close_prev"] = frame["close"].shift(1)
        frame["close_prev2"] = frame["close"].shift(2)
        frame["volume_prev"] = frame["volume"].shift(1)
        frame["ma5_prev"] = frame["ma5"].shift(1)
        frame["ma20_prev"] = frame["ma20"].shift(1)
        frame["ma60_prev"] = frame["ma60"].shift(1)
        frame["entry_open"] = frame["open"].shift(-1)
        frame["entry_low"] = frame["low"].shift(-1)

        for horizon in horizons:
            # T 收盘出信号；下一交易日开盘买；第 horizon+1 个开盘卖。
            frame[f"forward_{horizon}d"] = (
                frame["open"].shift(-(horizon + 1)) / frame["open"].shift(-1) - 1
            )

        parts.append(frame.reset_index().set_index(["instrument", "datetime"]))

    return pd.concat(parts).sort_index()


def _strategy_flags(snapshot: pd.DataFrame) -> pd.DataFrame:
    """复现 Sequoia-X V2 六个纯日线策略的上游条件。"""
    f = snapshot.copy()

    f["ma_volume"] = (
        (f["ma5_prev"] < f["ma20_prev"])
        & (f["ma5"] > f["ma20"])
        & (f["volume"] > f["vol_ma20"] * 1.5)
    )
    # qlib 的成交量单位为“手”，复权价×复权量保持成交额不变，再乘 100 股/手。
    turnover = f["close"] * f["volume"] * 100
    f["turtle_trade"] = (
        (f["close"] > f["high20_prev"])
        & (turnover > 100_000_000)
        & (f["close"] > f["open"])
        & (f["close"] > f["close_prev"])
    )
    f["high_tight_flag"] = (
        (f["high40"] / f["low40"] > 1.6)
        & (f["high10"] / f["low10"] < 1.15)
        & (f["low10"] >= f["high40"] * 0.8)
        & (f["volume"] < f["prev20_vol_mean"] * 0.6)
    )
    f["limit_up_shakeout"] = (
        (f["close_prev"] >= f["close_prev2"] * 1.095)
        & (f["close"] < f["open"])
        & (f["volume"] > f["volume_prev"] * 2.0)
        & (f["low"] >= f["close_prev"])
    )
    f["uptrend_limit_down"] = (
        (f["ma20_prev"] > f["ma60_prev"])
        & (f["close"] <= f["close_prev"] * 0.905)
        & (f["volume"] > f["vol_ma20"] * 2.0)
    )

    rps = f["ret120"].rank(pct=True) * 100
    f["rps_breakout"] = (rps >= 90) & (f["close"] >= f["high120"] * 0.90)
    f["rps"] = rps
    return f


def _uzi_stage(row: pd.Series) -> tuple[str, str]:
    close = row["close"]
    ma200, ma200_60ago = row["ma200"], row["ma200_60ago"]
    bullish_ma = row["ma5"] > row["ma10"] > row["ma20"] > row["ma60"] > row["ma120"]
    ma_align = "多头排列" if bullish_ma else "非多头"
    if pd.isna(ma200) or pd.isna(ma200_60ago):
        return "—", ma_align
    above = close > ma200
    rising = ma200 > ma200_60ago
    if above and rising:
        return "Stage 2 上升", ma_align
    if not above and rising:
        return "Stage 1 底部", ma_align
    if above and not rising:
        return "Stage 3 顶部", ma_align
    return "Stage 4 下跌", ma_align


def _load_uzi_scorer():
    scripts = str(UZI_SCRIPTS_DIR)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from lib.pipeline.score_fns import score_dimensions

    return score_dimensions


def _uzi_technical_score(row: pd.Series, scorer) -> tuple[int, str, str]:
    stage, ma_align = _uzi_stage(row)
    raw = {
        "ticker": str(row.name),
        "dimensions": {
            "2_kline": {
                "data": {
                    "stage": stage,
                    "ma_align": ma_align,
                    "kline_stats": {
                        "max_drawdown": f"{float(row['max_drawdown252']) * 100:.2f}%"
                    },
                }
            }
        }
    }
    score = int(scorer(raw)["dimensions"]["2_kline"]["score"])
    return score, stage, ma_align


def snapshot_for_date(enriched: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    try:
        snap = enriched.xs(date, level="datetime").copy()
    except KeyError:
        return pd.DataFrame()

    return _strategy_flags(snap)


def rank_candidates(snapshot: pd.DataFrame, scorer) -> pd.DataFrame:
    strategy_columns = list(STRATEGY_WEIGHTS)
    candidates = snapshot.loc[snapshot[strategy_columns].any(axis=1)].copy()
    if candidates.empty:
        return candidates

    candidates["strategy_score"] = sum(
        candidates[name].astype(int) * weight
        for name, weight in STRATEGY_WEIGHTS.items()
    )
    candidates["strategy_count"] = candidates[strategy_columns].sum(axis=1).astype(int)
    candidates["strategies"] = candidates[strategy_columns].apply(
        lambda row: [name for name, hit in row.items() if bool(hit)], axis=1
    )
    if scorer is not None:
        uzi = candidates.apply(lambda row: _uzi_technical_score(row, scorer), axis=1)
        candidates[["uzi_technical_score", "uzi_stage", "uzi_ma_align"]] = pd.DataFrame(
            uzi.tolist(), index=candidates.index
        )
    else:
        candidates["uzi_technical_score"] = 0
        candidates["uzi_stage"] = "disabled"
        candidates["uzi_ma_align"] = "disabled"
    candidates["sequoia_rank_score"] = (
        candidates["strategy_score"] * 10
        + candidates["strategy_count"] * 2
        + candidates["rps"].fillna(0) / 100
    )
    candidates["combined_score"] = (
        candidates["sequoia_rank_score"] + candidates["uzi_technical_score"]
    )
    return candidates.sort_values(
        ["sequoia_rank_score", "rps", "close"], ascending=False
    )


def _portfolio_result(
    frame: pd.DataFrame, horizons: tuple[int, ...], round_trip_cost: float
) -> dict[str, Any]:
    executable = frame.loc[~frame.get("entry_locked_limit", False)].copy()
    result: dict[str, Any] = {
        "selected_count": int(len(frame)),
        "executed_count": int(len(executable)),
    }
    for horizon in horizons:
        gross = executable[f"forward_{horizon}d"].dropna()
        values = gross - round_trip_cost
        result[f"return_{horizon}d"] = float(values.mean()) if not values.empty else None
        result[f"gross_return_{horizon}d"] = float(gross.mean()) if not gross.empty else None
        result[f"win_rate_{horizon}d"] = (
            float((values > 0).mean()) if not values.empty else None
        )
    return result


def _records(frame: pd.DataFrame, horizons: tuple[int, ...]) -> list[dict[str, Any]]:
    rows = []
    for instrument, row in frame.iterrows():
        item: dict[str, Any] = {
            "instrument": str(instrument),
            "strategies": row["strategies"],
            "strategy_score": int(row["strategy_score"]),
            "uzi_technical_score": int(row["uzi_technical_score"]),
            "uzi_stage": row["uzi_stage"],
            "rps": round(float(row["rps"]), 2) if pd.notna(row["rps"]) else None,
        }
        for horizon in horizons:
            value = row[f"forward_{horizon}d"]
            item[f"return_{horizon}d"] = float(value) if pd.notna(value) else None
        rows.append(item)
    return rows


def run(dates: list[str], config: BacktestConfig) -> dict[str, Any]:
    init_qlib()
    from qlib.data import D

    calendar = pd.DatetimeIndex(D.calendar(freq="day")).sort_values()
    requested = [pd.Timestamp(d) for d in dates]
    actual_dates = [calendar[calendar.searchsorted(d, side="left")] for d in requested]
    start_idx = max(0, int(calendar.searchsorted(min(actual_dates))) - 280)
    end_idx = min(
        len(calendar) - 1,
        int(calendar.searchsorted(max(actual_dates))) + max(config.horizons) + 2,
    )
    panel = load_panel(
        calendar[start_idx].strftime("%Y-%m-%d"),
        calendar[end_idx].strftime("%Y-%m-%d"),
    )
    enriched = add_indicators(panel, config.horizons)
    scorer = _load_uzi_scorer() if config.include_uzi else None

    date_results: list[dict[str, Any]] = []
    pure_frames: list[pd.DataFrame] = []
    combined_frames: list[pd.DataFrame] = []
    market_frames: list[pd.DataFrame] = []

    for requested_date, date in zip(requested, actual_dates):
        snapshot = snapshot_for_date(enriched, date)
        board20 = snapshot.index.to_series().str.match(r"^(SZ30|SH688)")
        limit_ratio = pd.Series(np.where(board20, 1.195, 1.095), index=snapshot.index)
        snapshot["entry_locked_limit"] = (
            (snapshot["entry_open"] >= snapshot["close"] * limit_ratio)
            & (snapshot["entry_low"] >= snapshot["close"] * limit_ratio)
        )
        ranked = rank_candidates(snapshot, scorer)
        pure = ranked.sort_values(
            ["sequoia_rank_score", "rps", "close"], ascending=False
        ).head(config.top_n)
        if config.include_uzi:
            combined = ranked.loc[
                ranked["uzi_technical_score"] >= config.uzi_min_score
            ].sort_values(
                ["combined_score", "rps", "close"], ascending=False
            ).head(config.top_n)
        else:
            combined = pure.copy()
        market = snapshot.dropna(subset=[f"forward_{h}d" for h in config.horizons])

        pure_frames.append(pure)
        combined_frames.append(combined)
        market_frames.append(market)
        date_results.append(
            {
                "requested_date": requested_date.strftime("%Y-%m-%d"),
                "signal_date": date.strftime("%Y-%m-%d"),
                "sequoia_union_count": int(len(ranked)),
                "sequoia_top": _portfolio_result(
                    pure, config.horizons, config.round_trip_cost
                ),
                "sequoia_uzi_gate": _portfolio_result(
                    combined, config.horizons, config.round_trip_cost
                ),
                "all_a_equal_weight": _portfolio_result(
                    market, config.horizons, config.round_trip_cost
                ),
                "sequoia_top_stocks": _records(pure, config.horizons),
                "combined_top_stocks": _records(combined, config.horizons),
            }
        )

    def aggregate(frames: list[pd.DataFrame]) -> dict[str, Any]:
        joined = pd.concat(frames) if frames else pd.DataFrame()
        return _portfolio_result(joined, config.horizons, config.round_trip_cost)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "method": {
            "signal": "T close",
            "entry": "T+1 open",
            "exit": "T+(horizon+1) open",
            "sequoia_source": "Sequoia-X V2 exact daily-rule reproduction",
            "uzi_scope": "original UZI score_dimensions, dimension 2 K-line only; Weinstein Stage and MA alignment reproduced from fetch_kline.py",
            "selection_ranking": "Sequoia group uses strategy-hit weights only; combined group applies UZI>=7 and uses UZI score as same-tier ranker",
            "lookahead_control": "all selection fields are at or before signal date",
            "execution_filter": "exclude T+1 one-price limit-up entries",
            "round_trip_cost": config.round_trip_cost,
            "warning": "This is not a historical replay of UZI news/fundamental dimensions; UZI has no as-of mode.",
        },
        "config": {
            "dates": dates,
            "top_n": config.top_n,
            "horizons": list(config.horizons),
            "uzi_min_score": config.uzi_min_score,
            "round_trip_cost": config.round_trip_cost,
            "include_uzi": config.include_uzi,
        },
        "dates": date_results,
        "aggregate": {
            "sequoia_top": aggregate(pure_frames),
            "sequoia_uzi_gate": aggregate(combined_frames),
            "all_a_equal_weight": aggregate(market_frames),
        },
    }


def write_report(result: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "sequoia_uzi_backtest_2026.json"
    md_path = output_dir / "sequoia_uzi_backtest_2026.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Sequoia-X + UZI 2026 历史截面试验",
        "",
        "> UZI 仅使用原版 K 线维度评分；当前新闻、财报、研报、资金流没有进入历史回测。",
        "",
        "| 信号日 | 候选数 | 重合 | Sequoia 5日 | 组合5日 | Sequoia 20日 | 组合20日 | 全A 5日 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["dates"]:
        combo = row["sequoia_uzi_gate"]
        pure = row["sequoia_top"]
        market = row["all_a_equal_weight"]
        pure_codes = {item["instrument"] for item in row["sequoia_top_stocks"]}
        combo_codes = {item["instrument"] for item in row["combined_top_stocks"]}
        overlap = len(pure_codes & combo_codes)
        pct = lambda value: "—" if value is None else f"{value:.2%}"
        lines.append(
            f"| {row['signal_date']} | {row['sequoia_union_count']} | {overlap}/10 | "
            f"{pct(pure['return_5d'])} | {pct(combo['return_5d'])} | "
            f"{pct(pure['return_20d'])} | {pct(combo['return_20d'])} | "
            f"{pct(market['return_5d'])} |"
        )
    lines.extend(["", "## 汇总", ""])
    for key, label in [
        ("sequoia_top", "Sequoia Top"),
        ("sequoia_uzi_gate", "Sequoia + UZI技术Gate"),
        ("all_a_equal_weight", "全A等权"),
    ]:
        row = result["aggregate"][key]
        lines.append(
            f"- {label}: 5日 {row['return_5d']:.2%}，10日 {row['return_10d']:.2%}，"
            f"20日 {row['return_20d']:.2%}（执行截面数 {row['executed_count']}）"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequoia-X + UZI 历史截面试验")
    parser.add_argument("--dates", nargs="+", default=DEFAULT_DATES)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--uzi-min-score", type=int, default=7)
    args = parser.parse_args()

    config = BacktestConfig(top_n=args.top, uzi_min_score=args.uzi_min_score)
    result = run(args.dates, config)
    json_path, md_path = write_report(result, OUTPUT_DIR)
    print(json.dumps(result["aggregate"], ensure_ascii=False, indent=2))
    print(f"JSON: {json_path}")
    print(f"Report: {md_path}")


if __name__ == "__main__":
    main()
