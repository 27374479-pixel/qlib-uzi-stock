"""
严格的 Qlib walk-forward 模型横评。

目标：
1. 使用交易日滚动窗口，并为两日未来收益标签设置 purge gap；
2. 在完全相同的数据、标签和窗口上比较 LightGBM / XGBoost；
3. 拼接所有折的样本外预测，再做一次连续 TopK 组合回测；
4. 同时报告信号质量和扣除交易成本后的组合表现。

示例：
    .venv\\Scripts\\python.exe walk_forward_backtest.py --quick
    .venv\\Scripts\\python.exe walk_forward_backtest.py ^
        --start 2025-07-01 --end 2026-07-03 --models lgb xgb
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import platform
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import OUTPUT_DIR, QLIB_DATA_DIR

os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

DEFAULT_MARKET = "csi800"
LABEL_EXPR = "Ref($close, -2) / Ref($close, -1) - 1"
LABEL_PRESETS = {
    "close_1d": {
        "expression": LABEL_EXPR,
        "price_field": "$close",
        "description": "T信号，T+1收盘成交，持有至T+2收盘",
    },
    "open_1d": {
        "expression": "Ref($open, -2) / Ref($open, -1) - 1",
        "price_field": "$open",
        "description": "T信号，T+1开盘成交，持有至T+2开盘",
    },
}
ANNUALIZATION = 252
_MARKET_DATA_CACHE: dict[
    tuple[str, str, str, str, tuple[str, ...]],
    tuple[pd.DataFrame, pd.DataFrame, pd.Series],
] = {}


@dataclass(frozen=True)
class Fold:
    fold_id: int
    train_start: str
    train_end: str
    valid_start: str
    valid_end: str
    test_start: str
    test_end: str


def init_qlib() -> None:
    import qlib
    from qlib.constant import REG_CN

    qlib.init(provider_uri=str(QLIB_DATA_DIR), region=REG_CN)


def trading_calendar() -> pd.DatetimeIndex:
    from qlib.data import D

    return pd.DatetimeIndex(D.calendar(freq="day")).sort_values()


def _date_at_or_after(calendar: pd.DatetimeIndex, value: str) -> int:
    idx = int(calendar.searchsorted(pd.Timestamp(value), side="left"))
    if idx >= len(calendar):
        raise ValueError(f"{value} 超出本地数据日历")
    return idx


def _date_at_or_before(calendar: pd.DatetimeIndex, value: str) -> int:
    idx = int(calendar.searchsorted(pd.Timestamp(value), side="right")) - 1
    if idx < 0:
        raise ValueError(f"{value} 早于本地数据日历")
    return idx


def make_folds(
    calendar: pd.DatetimeIndex,
    start: str,
    end: str,
    train_days: int = 756,
    valid_days: int = 63,
    test_days: int = 21,
    purge_days: int = 2,
    max_folds: int | None = None,
) -> list[Fold]:
    """按交易日生成互不重叠的测试折。"""
    first_test = _date_at_or_after(calendar, start)
    final_test = _date_at_or_before(calendar, end)
    min_history = train_days + valid_days + purge_days * 2
    if first_test < min_history:
        first_test = min_history

    folds: list[Fold] = []
    test_start_idx = first_test
    fold_id = 0

    while test_start_idx <= final_test:
        test_end_idx = min(test_start_idx + test_days - 1, final_test)
        valid_end_idx = test_start_idx - purge_days - 1
        valid_start_idx = valid_end_idx - valid_days + 1
        train_end_idx = valid_start_idx - purge_days - 1
        train_start_idx = train_end_idx - train_days + 1
        if train_start_idx < 0:
            raise ValueError("历史数据不足以构造指定滚动窗口")

        fmt = lambda i: calendar[i].strftime("%Y-%m-%d")
        folds.append(
            Fold(
                fold_id=fold_id,
                train_start=fmt(train_start_idx),
                train_end=fmt(train_end_idx),
                valid_start=fmt(valid_start_idx),
                valid_end=fmt(valid_end_idx),
                test_start=fmt(test_start_idx),
                test_end=fmt(test_end_idx),
            )
        )
        fold_id += 1
        if max_folds is not None and len(folds) >= max_folds:
            break
        test_start_idx = test_end_idx + 1

    return folds


def build_dataset(fold: Fold, market: str, label_expr: str = LABEL_EXPR):
    from qlib.utils import init_instance_by_config

    handler_config = {
        "class": "Alpha158",
        "module_path": "qlib.contrib.data.handler",
        "kwargs": {
            "instruments": market,
            "start_time": fold.train_start,
            "end_time": fold.test_end,
            "fit_start_time": fold.train_start,
            "fit_end_time": fold.train_end,
            "infer_processors": [
                {
                    "class": "RobustZScoreNorm",
                    "kwargs": {"fields_group": "feature", "clip_outlier": True},
                },
                {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
            ],
            "learn_processors": [
                {"class": "DropnaLabel"},
                {"class": "CSRankNorm", "kwargs": {"fields_group": "label"}},
            ],
            "label": [label_expr],
        },
    }
    return init_instance_by_config(
        {
            "class": "DatasetH",
            "module_path": "qlib.data.dataset",
            "kwargs": {
                "handler": handler_config,
                "segments": {
                    "train": (fold.train_start, fold.train_end),
                    "valid": (fold.valid_start, fold.valid_end),
                    "test": (fold.test_start, fold.test_end),
                },
            },
        }
    )


def build_model(model_name: str, seed: int):
    if model_name == "lgb":
        from qlib.contrib.model.gbdt import LGBModel

        return LGBModel(
            loss="mse",
            num_boost_round=300,
            early_stopping_rounds=30,
            learning_rate=0.0421,
            colsample_bytree=0.8879,
            subsample=0.8789,
            lambda_l1=205.6999,
            lambda_l2=580.9768,
            max_depth=8,
            num_leaves=210,
            num_threads=4,
            seed=seed,
            feature_fraction_seed=seed,
            bagging_seed=seed,
            data_random_seed=seed,
            deterministic=True,
        )
    if model_name == "xgb":
        from qlib.contrib.model.xgboost import XGBModel

        return XGBModel(
            objective="reg:squarederror",
            eval_metric="rmse",
            eta=0.0421,
            colsample_bytree=0.8879,
            subsample=0.8789,
            max_depth=8,
            nthread=4,
            seed=seed,
            tree_method="hist",
        )
    raise ValueError(f"不支持的模型: {model_name}")


def _set_seed(seed: int) -> None:
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)


def _series(value: pd.Series | pd.DataFrame, name: str) -> pd.Series:
    if isinstance(value, pd.DataFrame):
        if value.shape[1] != 1:
            raise ValueError(f"{name} 预期单列，实际 {value.shape[1]} 列")
        value = value.iloc[:, 0]
    result = value.rename(name).sort_index()
    if result.index.names != ["datetime", "instrument"]:
        result.index = result.index.set_names(["datetime", "instrument"])
    return result


def _feature_hash(dataset) -> str:
    from qlib.data.dataset.handler import DataHandlerLP

    sample = dataset.prepare(
        "train", col_set="feature", data_key=DataHandlerLP.DK_I
    )
    columns = [str(c) for c in sample.columns]
    return hashlib.sha256("\n".join(columns).encode("utf-8")).hexdigest()


def train_fold(
    fold: Fold,
    model_name: str,
    market: str,
    output_root: Path,
    base_seed: int,
    label_expr: str = LABEL_EXPR,
) -> tuple[pd.Series, pd.Series, dict[str, Any]]:
    from qlib.data.dataset.handler import DataHandlerLP

    seed = base_seed + fold.fold_id
    _set_seed(seed)
    fold_dir = output_root / model_name / f"fold_{fold.fold_id:03d}"
    fold_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    dataset = build_dataset(fold, market, label_expr=label_expr)
    feature_hash = _feature_hash(dataset)
    model = build_model(model_name, seed)
    evals_result: dict[str, Any] = {}

    if model_name == "xgb":
        model.fit(
            dataset,
            num_boost_round=300,
            early_stopping_rounds=30,
            verbose_eval=False,
            evals_result=evals_result,
        )
    else:
        model.fit(dataset, verbose_eval=0, evals_result=evals_result)

    prediction = _series(model.predict(dataset, segment="test"), "score")
    raw_label = dataset.prepare(
        "test", col_set="label", data_key=DataHandlerLP.DK_R
    )
    label = _series(raw_label, "label")

    if prediction.index.duplicated().any():
        raise ValueError(f"{model_name} fold {fold.fold_id} 预测索引重复")

    metadata = {
        **asdict(fold),
        "model": model_name,
        "market": market,
        "label": label_expr,
        "seed": seed,
        "feature_hash": feature_hash,
        "n_predictions": int(prediction.notna().sum()),
        "n_labels": int(label.notna().sum()),
        "elapsed_seconds": round(time.time() - started, 2),
        "python": platform.python_version(),
    }

    prediction.to_pickle(fold_dir / "pred.pkl")
    label.to_pickle(fold_dir / "label.pkl")
    with (fold_dir / "model.pkl").open("wb") as file:
        pickle.dump(model, file)
    (fold_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return prediction, label, metadata


def signal_metrics(prediction: pd.Series, label: pd.Series) -> tuple[dict[str, Any], pd.DataFrame]:
    from qlib.contrib.eva.alpha import calc_ic

    aligned = pd.concat([prediction, label], axis=1).dropna()
    ic, rank_ic = calc_ic(aligned["score"], aligned["label"], dropna=True)
    daily = pd.DataFrame({"ic": ic, "rank_ic": rank_ic}).sort_index()

    def summarize(series: pd.Series, prefix: str) -> dict[str, float]:
        clean = series.dropna()
        std = clean.std(ddof=1)
        return {
            f"{prefix}_mean": float(clean.mean()),
            f"{prefix}_std": float(std),
            f"{prefix}_positive_rate": float((clean > 0).mean()),
            f"{prefix}_ir_qlib": float(clean.mean() / std) if std > 0 else np.nan,
            f"{prefix}_ir_annualized": (
                float(clean.mean() / std * np.sqrt(ANNUALIZATION))
                if std > 0
                else np.nan
            ),
        }

    metrics: dict[str, Any] = {
        "n_observations": int(len(aligned)),
        "n_days": int(aligned.index.get_level_values("datetime").nunique()),
    }
    metrics.update(summarize(daily["ic"], "ic"))
    metrics.update(summarize(daily["rank_ic"], "rank_ic"))
    return metrics, daily


def run_portfolio_backtest(
    prediction: pd.Series,
    topk: int,
    n_drop: int,
    benchmark: str,
    open_cost: float,
    close_cost: float,
    price_field: str = "$close",
) -> tuple[dict[str, Any], pd.DataFrame]:
    from qlib.contrib.evaluate import risk_analysis
    from qlib.data import D

    # Qlib 0.9.7 的 Exchange 在部分 Windows/NumPy 2 环境会触发原生崩溃。
    # 此处保留 TopK dropout 核心规则，以明确的 T 信号 -> T+1 收盘成交
    # -> T+2 收盘开始计收益时序做连续模拟，避免同日收盘前视。
    signal_dates = pd.DatetimeIndex(
        prediction.index.get_level_values("datetime").unique()
    ).sort_values()
    calendar = trading_calendar()
    first_signal_idx = int(calendar.searchsorted(signal_dates.min(), side="left"))
    last_signal_idx = int(calendar.searchsorted(signal_dates.max(), side="left"))
    price_start_idx = max(0, first_signal_idx)
    price_end_idx = min(len(calendar) - 1, last_signal_idx + 2)
    price_dates = calendar[price_start_idx : price_end_idx + 1]

    instruments = sorted(
        prediction.index.get_level_values("instrument").unique().tolist()
    )
    cache_key = (
        str(price_dates.min().date()),
        str(price_dates.max().date()),
        benchmark,
        price_field,
        tuple(instruments),
    )
    cached = _MARKET_DATA_CACHE.get(cache_key)
    if cached is None:
        close_raw = D.features(
            instruments,
            [price_field],
            start_time=price_dates.min(),
            end_time=price_dates.max(),
            freq="day",
        )
        close_raw.columns = ["close"]
        close = close_raw["close"].unstack("instrument").sort_index()
        stock_returns = close.pct_change(fill_method=None)

        bench_raw = D.features(
            [benchmark],
            [price_field],
            start_time=price_dates.min(),
            end_time=price_dates.max(),
            freq="day",
        )
        bench_raw.columns = ["close"]
        bench_close = bench_raw["close"].droplevel("instrument").sort_index()
        bench_returns = bench_close.pct_change(fill_method=None)
        _MARKET_DATA_CACHE[cache_key] = (close, stock_returns, bench_returns)
    else:
        close, stock_returns, bench_returns = cached

    signal_by_date = {
        pd.Timestamp(date): group.droplevel("datetime").sort_values(ascending=False)
        for date, group in prediction.groupby(level="datetime")
    }
    trade_signal: dict[pd.Timestamp, pd.Series] = {}
    for signal_date, scores in signal_by_date.items():
        idx = int(calendar.searchsorted(signal_date, side="left"))
        if idx + 1 < len(calendar):
            trade_signal[pd.Timestamp(calendar[idx + 1])] = scores

    holdings: list[str] = []
    risk_degree = 0.95
    records: list[dict[str, Any]] = []

    for date in close.index:
        date = pd.Timestamp(date)
        gross_return = 0.0
        if holdings:
            available_returns = stock_returns.loc[date].reindex(holdings).dropna()
            if not available_returns.empty:
                gross_return = float(available_returns.mean() * risk_degree)

        buy_turnover = sell_turnover = 0.0
        scores = trade_signal.get(date)
        if scores is not None:
            tradable = close.loc[date].dropna().index
            ranked = scores.reindex(tradable).dropna().sort_values(ascending=False)
            desired = ranked.head(topk).index.tolist()

            if not holdings:
                new_holdings = desired
            else:
                current_ranked = (
                    ranked.reindex(holdings).dropna().sort_values(ascending=False)
                )
                keep = current_ranked.index.tolist()
                forced_out = [stock for stock in holdings if stock not in ranked.index]
                eligible_sell = [stock for stock in keep if stock not in desired]
                sell_count = min(n_drop, len(eligible_sell))
                sold = set(forced_out + eligible_sell[-sell_count:])
                survivors = [stock for stock in holdings if stock not in sold]
                additions = [stock for stock in desired if stock not in survivors]
                new_holdings = (survivors + additions)[:topk]

            old_set, new_set = set(holdings), set(new_holdings)
            denominator = max(topk, 1)
            buy_turnover = len(new_set - old_set) / denominator * risk_degree
            sell_turnover = len(old_set - new_set) / denominator * risk_degree
            holdings = new_holdings

        cost = buy_turnover * open_cost + sell_turnover * close_cost
        records.append(
            {
                "datetime": date,
                "return": gross_return,
                "cost": cost,
                "bench": float(bench_returns.get(date, np.nan)),
                "turnover": buy_turnover + sell_turnover,
                "n_holdings": len(holdings),
            }
        )

    report = pd.DataFrame(records).set_index("datetime")
    # 首次建仓当天只发生交易成本，下一交易日起才有持仓收益；保留该成本。
    report = report.loc[report["n_holdings"].cummax() > 0].copy()
    report["bench"] = report["bench"].fillna(0.0)
    net = report["return"] - report["cost"]
    excess = net - report["bench"]
    absolute_risk = risk_analysis(net, N=ANNUALIZATION, freq=None, mode="product")["risk"]
    excess_risk = risk_analysis(excess, N=ANNUALIZATION, freq=None, mode="product")["risk"]

    metrics = {
        "start": str(report.index.min().date()),
        "end": str(report.index.max().date()),
        "trading_days": int(len(report)),
        "topk": topk,
        "n_drop": n_drop,
        "open_cost": open_cost,
        "close_cost": close_cost,
        "cumulative_return": float((1 + net).prod() - 1),
        "benchmark_return": float((1 + report["bench"]).prod() - 1),
        "excess_return": float((1 + excess).prod() - 1),
        "annualized_return": float(absolute_risk["annualized_return"]),
        "information_ratio": float(excess_risk["information_ratio"]),
        "max_drawdown": float(absolute_risk["max_drawdown"]),
        "mean_daily_turnover": float(report["turnover"].mean()),
        "total_cost": float(report["cost"].sum()),
        "positive_day_rate": float((net > 0).mean()),
        "execution_assumption": (
            f"signal T -> rebalance at T+1 {price_field} "
            f"-> earn from T+1 to T+2 {price_field}"
        ),
        "simulator": "native_topk_dropout_windows_safe",
    }
    return metrics, report


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qlib walk-forward 模型横评")
    parser.add_argument("--start", default="2025-07-01")
    parser.add_argument("--end", default="2026-07-03")
    parser.add_argument("--models", nargs="+", choices=["lgb", "xgb"], default=["lgb", "xgb"])
    parser.add_argument("--market", default=DEFAULT_MARKET)
    parser.add_argument("--train-days", type=int, default=756)
    parser.add_argument("--valid-days", type=int, default=63)
    parser.add_argument("--test-days", type=int, default=21)
    parser.add_argument("--purge-days", type=int, default=2)
    parser.add_argument("--topk", type=int, default=50)
    parser.add_argument("--n-drop", type=int, default=5)
    parser.add_argument("--benchmark", default="SH000300")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--label-preset",
        choices=sorted(LABEL_PRESETS),
        default="close_1d",
        help="预测标签与成交价格口径",
    )
    parser.add_argument("--max-folds", type=int)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快速冒烟：最近两个 10 日测试折、504 日训练窗",
    )
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    init_qlib()
    calendar = trading_calendar()
    label_config = LABEL_PRESETS[args.label_preset]

    if args.quick:
        args.train_days = 504
        args.valid_days = 42
        args.test_days = 10
        if args.max_folds is None:
            args.max_folds = 2
        quick_start_idx = max(0, len(calendar) - args.test_days * args.max_folds)
        args.start = calendar[quick_start_idx].strftime("%Y-%m-%d")
        args.end = calendar[-1].strftime("%Y-%m-%d")

    folds = make_folds(
        calendar,
        start=args.start,
        end=args.end,
        train_days=args.train_days,
        valid_days=args.valid_days,
        test_days=args.test_days,
        purge_days=args.purge_days,
        max_folds=args.max_folds,
    )
    if not folds:
        raise ValueError("未生成任何 walk-forward 折")

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = OUTPUT_DIR / "walk_forward" / run_stamp
    output_root.mkdir(parents=True, exist_ok=True)
    config = vars(args) | {
        "label_expression": label_config["expression"],
        "execution_price": label_config["price_field"],
        "label_description": label_config["description"],
        "folds": [asdict(fold) for fold in folds],
    }
    (output_root / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary: dict[str, Any] = {"run": run_stamp, "config": config, "models": {}}
    print(f"输出目录: {output_root}")
    print(f"滚动折数: {len(folds)} | 模型: {', '.join(args.models)}")

    for model_name in args.models:
        print(f"\n{'=' * 72}\n模型: {model_name.upper()}\n{'=' * 72}")
        predictions: list[pd.Series] = []
        labels: list[pd.Series] = []
        fold_metadata: list[dict[str, Any]] = []

        for fold in folds:
            print(
                f"[{fold.fold_id + 1}/{len(folds)}] "
                f"train {fold.train_start}~{fold.train_end} | "
                f"test {fold.test_start}~{fold.test_end}"
            )
            pred, label, metadata = train_fold(
                fold,
                model_name,
                args.market,
                output_root,
                args.seed,
                label_expr=label_config["expression"],
            )
            predictions.append(pred)
            labels.append(label)
            fold_metadata.append(metadata)
            print(
                f"  预测 {metadata['n_predictions']:,} 条，"
                f"耗时 {metadata['elapsed_seconds']:.1f}s"
            )

        pred_oos = pd.concat(predictions).sort_index()
        label_oos = pd.concat(labels).sort_index()
        if pred_oos.index.duplicated().any():
            duplicates = int(pred_oos.index.duplicated().sum())
            raise ValueError(f"{model_name} OOS 预测存在 {duplicates} 个重复索引")

        model_dir = output_root / model_name
        pred_oos.to_pickle(model_dir / "pred_oos.pkl")
        label_oos.to_pickle(model_dir / "label_oos.pkl")

        signal, daily_ic = signal_metrics(pred_oos, label_oos)
        portfolio, report = run_portfolio_backtest(
            pred_oos,
            topk=args.topk,
            n_drop=args.n_drop,
            benchmark=args.benchmark,
            open_cost=0.0003,
            close_cost=0.0013,
            price_field=label_config["price_field"],
        )
        daily_ic.to_csv(model_dir / "daily_ic.csv", encoding="utf-8-sig")
        report.to_csv(model_dir / "portfolio_daily.csv", encoding="utf-8-sig")

        summary["models"][model_name] = {
            "folds": fold_metadata,
            "signal": signal,
            "portfolio": portfolio,
        }
        print(
            f"  IC={signal['ic_mean']:.4f} | RankIC={signal['rank_ic_mean']:.4f} | "
            f"年化={portfolio['annualized_return']:.2%} | "
            f"IR={portfolio['information_ratio']:.3f} | "
            f"MDD={portfolio['max_drawdown']:.2%}"
        )

    safe_summary = _json_safe(summary)
    (output_root / "summary.json").write_text(
        json.dumps(safe_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "walk_forward_latest.json").write_text(
        json.dumps(safe_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n汇总: {output_root / 'summary.json'}")
    return safe_summary


if __name__ == "__main__":
    main()
