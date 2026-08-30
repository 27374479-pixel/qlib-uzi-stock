"""
使用已生成的 walk-forward 样本外预测做排名集成与留出验证。

严格约束：
- 只使用 pred_oos，不重新接触训练/验证数据；
- 前 N-2 折用于选择 signal/topk/n_drop；
- 最后 2 折作为留出集，只评估一次；
- 输出校准排名、留出表现和最终配置，不改生产模型。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import OUTPUT_DIR
from walk_forward_backtest import init_qlib, run_portfolio_backtest, signal_metrics


def rank_normalize(prediction: pd.Series) -> pd.Series:
    """逐日映射到 [0, 1]，消除不同模型分数尺度差异。"""
    return prediction.groupby(level="datetime", group_keys=False).rank(pct=True)


def build_signals(run_dir: Path) -> tuple[dict[str, pd.Series], pd.Series]:
    lgb = pd.read_pickle(run_dir / "lgb" / "pred_oos.pkl").rename("lgb")
    xgb = pd.read_pickle(run_dir / "xgb" / "pred_oos.pkl").rename("xgb")
    label = pd.read_pickle(run_dir / "lgb" / "label_oos.pkl").rename("label")
    aligned = pd.concat([lgb, xgb], axis=1, join="inner").dropna()

    lgb_rank = rank_normalize(aligned["lgb"]).rename("score")
    xgb_rank = rank_normalize(aligned["xgb"]).rename("score")
    equal_rank = ((lgb_rank + xgb_rank) / 2).rename("score")
    # XGB 在半年 OOS 中优于 LGB；仅加入一个预先限定的轻度倾斜组合，
    # 避免在连续权重上做大规模样本内搜索。
    xgb_tilt = (0.35 * lgb_rank + 0.65 * xgb_rank).rename("score")
    return {
        "lgb_rank": lgb_rank,
        "xgb_rank": xgb_rank,
        "equal_rank": equal_rank,
        "xgb_tilt_65": xgb_tilt,
    }, label


def split_by_holdout(
    series: pd.Series, holdout_start: pd.Timestamp
) -> tuple[pd.Series, pd.Series]:
    dates = series.index.get_level_values("datetime")
    return series[dates < holdout_start], series[dates >= holdout_start]


def evaluate(
    prediction: pd.Series,
    label: pd.Series,
    topk: int,
    n_drop: int,
) -> dict[str, Any]:
    signal, _ = signal_metrics(prediction, label)
    portfolio, _ = run_portfolio_backtest(
        prediction,
        topk=topk,
        n_drop=n_drop,
        benchmark="SH000300",
        open_cost=0.0003,
        close_cost=0.0013,
    )
    return {"signal_metrics": signal, "portfolio": portfolio}


def calibration_score(result: dict[str, Any]) -> float:
    """以成本后超额和 IR 为主，回撤作轻惩罚；只用于校准集排序。"""
    portfolio = result["portfolio"]
    return float(
        portfolio["excess_return"]
        + 0.02 * portfolio["information_ratio"]
        + 0.10 * portfolio["max_drawdown"]
    )


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OOS 预测排名集成与留出验证")
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=OUTPUT_DIR / "walk_forward" / "20260712_224427",
    )
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    folds = config["folds"]
    if len(folds) < 4:
        raise ValueError("至少需要 4 个 walk-forward 折才能做校准/留出拆分")
    holdout_start = pd.Timestamp(folds[-2]["test_start"])

    init_qlib()
    signals, label = build_signals(run_dir)
    calibration_rows: list[dict[str, Any]] = []
    grids = [(20, 2), (30, 3), (50, 5), (100, 10)]

    for signal_name, prediction in signals.items():
        pred_cal, _ = split_by_holdout(prediction, holdout_start)
        label_cal, _ = split_by_holdout(label, holdout_start)
        for topk, n_drop in grids:
            result = evaluate(pred_cal, label_cal, topk, n_drop)
            calibration_rows.append(
                {
                    "signal": signal_name,
                    "topk": topk,
                    "n_drop": n_drop,
                    "score": calibration_score(result),
                    **result,
                }
            )

    calibration_rows.sort(key=lambda row: row["score"], reverse=True)
    winner = calibration_rows[0]
    winner_signal = signals[winner["signal"]]
    _, pred_holdout = split_by_holdout(winner_signal, holdout_start)
    _, label_holdout = split_by_holdout(label, holdout_start)
    holdout = evaluate(
        pred_holdout,
        label_holdout,
        topk=winner["topk"],
        n_drop=winner["n_drop"],
    )

    # 同配置下比较各单模型和集成，防止“参数胜出”被误解成“信号胜出”。
    holdout_comparison: dict[str, Any] = {}
    for signal_name, prediction in signals.items():
        _, pred_part = split_by_holdout(prediction, holdout_start)
        holdout_comparison[signal_name] = evaluate(
            pred_part,
            label_holdout,
            topk=winner["topk"],
            n_drop=winner["n_drop"],
        )

    output = {
        "source_run": str(run_dir),
        "methodology": {
            "calibration_folds": len(folds) - 2,
            "holdout_folds": 2,
            "holdout_start": holdout_start,
            "signals": list(signals),
            "grid": [{"topk": topk, "n_drop": n_drop} for topk, n_drop in grids],
            "selection_metric": "excess_return + 0.02*IR + 0.10*max_drawdown",
        },
        "winner": {
            "signal": winner["signal"],
            "topk": winner["topk"],
            "n_drop": winner["n_drop"],
            "calibration": {
                "score": winner["score"],
                "signal": winner["signal"],
                "portfolio": winner["portfolio"],
            },
            "holdout": holdout,
        },
        "calibration_ranking": calibration_rows,
        "holdout_comparison_same_config": holdout_comparison,
    }
    safe = json_safe(output)
    out_path = run_dir / "ensemble_optimization.json"
    out_path.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "ensemble_optimization_latest.json").write_text(
        json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"校准冠军: {winner['signal']} Top{winner['topk']}/drop{winner['n_drop']}"
    )
    print(
        "留出集: "
        f"累计={holdout['portfolio']['cumulative_return']:.2%}, "
        f"超额={holdout['portfolio']['excess_return']:.2%}, "
        f"IR={holdout['portfolio']['information_ratio']:.3f}, "
        f"MDD={holdout['portfolio']['max_drawdown']:.2%}, "
        f"RankIC={holdout['signal_metrics']['rank_ic_mean']:.4f}"
    )
    print(f"结果: {out_path}")
    return safe


if __name__ == "__main__":
    main()
