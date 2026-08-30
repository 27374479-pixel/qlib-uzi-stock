"""Sequoia-X Top 10 的 2024-2026 扩展非重叠截面回测。"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from config import OUTPUT_DIR
from sequoia_uzi_backtest import BacktestConfig, init_qlib, run


def choose_dates(start: str, end: str, step: int) -> list[str]:
    init_qlib()
    from qlib.data import D

    calendar = pd.DatetimeIndex(D.calendar(freq="day")).sort_values()
    first = int(calendar.searchsorted(pd.Timestamp(start), side="left"))
    last = int(calendar.searchsorted(pd.Timestamp(end), side="right"))
    return [d.strftime("%Y-%m-%d") for d in calendar[first:last:step]]


def metric(values: list[float]) -> dict[str, Any]:
    series = pd.Series(values, dtype=float).dropna()
    if series.empty:
        return {"count": 0}
    n = len(series)
    mean = float(series.mean())
    std = float(series.std(ddof=1)) if n > 1 else 0.0
    sem = std / math.sqrt(n) if n > 1 else 0.0
    critical = float(stats.t.ppf(0.975, n - 1)) if n > 1 else 0.0
    return {
        "count": n,
        "mean": mean,
        "median": float(series.median()),
        "std": std,
        "win_rate": float((series > 0).mean()),
        "worst": float(series.min()),
        "best": float(series.max()),
        "ci95_low": mean - critical * sem,
        "ci95_high": mean + critical * sem,
    }


def max_drawdown(returns: list[float]) -> float:
    equity = np.cumprod(1 + np.asarray(returns, dtype=float))
    if not len(equity):
        return float("nan")
    peak = np.maximum.accumulate(np.r_[1.0, equity])
    curve = np.r_[1.0, equity]
    return float(np.min(curve / peak - 1))


def analyze(result: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for item in result["dates"]:
        pure = item["sequoia_top"]
        market = item["all_a_equal_weight"]
        row: dict[str, Any] = {"date": item["signal_date"]}
        for horizon in (5, 10, 20):
            stock_ret = pure[f"return_{horizon}d"]
            market_ret = market[f"return_{horizon}d"]
            row[f"return_{horizon}d"] = stock_ret
            row[f"market_{horizon}d"] = market_ret
            row[f"excess_{horizon}d"] = stock_ret - market_ret
        rows.append(row)

    summary: dict[str, Any] = {}
    for horizon in (5, 10, 20):
        summary[f"return_{horizon}d"] = metric(
            [r[f"return_{horizon}d"] for r in rows]
        )
        summary[f"excess_{horizon}d"] = metric(
            [r[f"excess_{horizon}d"] for r in rows]
        )

    twenty = [r["return_20d"] for r in rows]
    summary["sequential_20d"] = {
        "periods": len(twenty),
        "cumulative_return": float(np.prod(1 + np.asarray(twenty)) - 1),
        "max_drawdown": max_drawdown(twenty),
    }

    by_year: dict[str, Any] = {}
    frame = pd.DataFrame(rows)
    frame["year"] = frame["date"].str[:4]
    for year, group in frame.groupby("year"):
        by_year[str(year)] = {
            f"return_{h}d": metric(group[f"return_{h}d"].tolist())
            for h in (5, 10, 20)
        }
        by_year[str(year)].update(
            {
                f"excess_{h}d": metric(group[f"excess_{h}d"].tolist())
                for h in (5, 10, 20)
            }
        )

    return {"rows": rows, "summary": summary, "by_year": by_year}


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.2%}"


def write_outputs(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    first_year = payload["scope"]["start"][:4]
    last_year = payload["scope"]["end"][:4]
    suffix = f"{first_year}_{last_year}"
    json_path = output_dir / f"sequoia_extended_backtest_{suffix}.json"
    md_path = output_dir / f"sequoia_extended_backtest_{suffix}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    analysis = payload["analysis"]
    lines = [
        f"# Sequoia-X Top 10 扩展回测（{first_year}-{last_year}）",
        "",
        "> 每 21 个交易日取一个截面；T+1 开盘买入，扣除 0.2% 往返成本，并排除次日一字涨停。",
        "",
        "## 总体结果",
        "",
        "| 持有期 | 平均收益 | 中位数 | 胜率 | 95% CI | 平均超额 | 超额胜率 | 最差 | 最好 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for h in (5, 10, 20):
        ret = analysis["summary"][f"return_{h}d"]
        excess = analysis["summary"][f"excess_{h}d"]
        lines.append(
            f"| {h}日 | {pct(ret['mean'])} | {pct(ret['median'])} | {pct(ret['win_rate'])} | "
            f"[{pct(ret['ci95_low'])}, {pct(ret['ci95_high'])}] | {pct(excess['mean'])} | "
            f"{pct(excess['win_rate'])} | {pct(ret['worst'])} | {pct(ret['best'])} |"
        )

    seq = analysis["summary"]["sequential_20d"]
    lines.extend(
        [
            "",
            f"20日非重叠序列累计收益：{pct(seq['cumulative_return'])}；最大回撤：{pct(seq['max_drawdown'])}。",
            "",
            "## 年度分解（20日）",
            "",
            "| 年份 | 截面数 | 平均收益 | 中位数 | 胜率 | 平均超额 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for year, data in analysis["by_year"].items():
        ret = data["return_20d"]
        excess = data["excess_20d"]
        lines.append(
            f"| {year} | {ret['count']} | {pct(ret['mean'])} | {pct(ret['median'])} | "
            f"{pct(ret['win_rate'])} | {pct(excess['mean'])} |"
        )

    lines.extend(
        [
            "",
            "## 每期20日收益",
            "",
            "| 日期 | Top 10 | 全A | 超额 |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in analysis["rows"]:
        lines.append(
            f"| {row['date']} | {pct(row['return_20d'])} | {pct(row['market_20d'])} | "
            f"{pct(row['excess_20d'])} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequoia-X Top 10 扩展回测")
    parser.add_argument("--start", default="2024-01-05")
    parser.add_argument("--end", default="2026-06-01")
    parser.add_argument("--step", type=int, default=21)
    args = parser.parse_args()

    dates = choose_dates(args.start, args.end, args.step)
    config = BacktestConfig(top_n=10, include_uzi=False)
    raw = run(dates, config)
    payload = {
        "scope": {
            "start": args.start,
            "end": args.end,
            "step_trading_days": args.step,
            "dates": dates,
            "top_n": 10,
        },
        "analysis": analyze(raw),
        "raw": raw,
    }
    json_path, md_path = write_outputs(payload, OUTPUT_DIR)
    print(json.dumps(payload["analysis"]["summary"], ensure_ascii=False, indent=2))
    print(f"JSON: {json_path}")
    print(f"Report: {md_path}")


if __name__ == "__main__":
    main()
