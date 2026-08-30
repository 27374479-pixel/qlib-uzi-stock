"""
qlib_select.py — 用 qlib LightGBM 模型选出当天候选股

流程:
  1. 初始化 qlib，加载 A 股数据
  2. 用内置 Alpha158 因子 + LightGBM 训练/加载模型
  3. 预测今日收益排序，输出 Top-N 候选
"""

import os
import sys
import json
import warnings
from datetime import datetime, timedelta
from pathlib import Path

os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


def init_qlib(provider_uri: str):
    import qlib
    from qlib.constant import REG_CN
    qlib.init(provider_uri=provider_uri, region=REG_CN)


def get_data_date_range():
    """获取 qlib 数据的日期范围"""
    from qlib.data import D
    cal = D.calendar(freq="day")
    return cal[0], cal[-1]


def build_dataset(train_start, train_end, valid_start, valid_end, test_start, test_end,
                  market="csi800"):
    """构建 Alpha158 因子数据集"""
    from qlib.contrib.data.handler import Alpha158
    from qlib.utils import init_instance_by_config

    handler_config = {
        "class": "Alpha158",
        "module_path": "qlib.contrib.data.handler",
        "kwargs": {
            "instruments": market,
            "start_time": train_start,
            "end_time": test_end,
            "fit_start_time": train_start,
            "fit_end_time": train_end,
            "infer_processors": [
                {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
                {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
            ],
            "learn_processors": [
                {"class": "DropnaLabel"},
                {"class": "CSRankNorm", "kwargs": {"fields_group": "label"}},
            ],
            "label": ["Ref($close, -2) / Ref($close, -1) - 1"],
        },
    }

    dataset_config = {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": handler_config,
            "segments": {
                "train": (train_start, train_end),
                "valid": (valid_start, valid_end),
                "test": (test_start, test_end),
            },
        },
    }

    dataset = init_instance_by_config(dataset_config)
    return dataset


def train_lgb_model(dataset, model_save_path: str = None):
    """训练 LightGBM 模型"""
    from qlib.contrib.model.gbdt import LGBModel

    model = LGBModel(
        loss="mse",
        colsample_bytree=0.8879,
        learning_rate=0.0421,
        subsample=0.8789,
        lambda_l1=205.6999,
        lambda_l2=580.9768,
        max_depth=8,
        num_leaves=210,
        num_threads=4,
    )
    model.fit(dataset)

    if model_save_path:
        import pickle
        Path(model_save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(model_save_path, "wb") as f:
            pickle.dump(model, f)
        print(f"[qlib] 模型已保存: {model_save_path}")

    return model


def load_model(model_path: str):
    """加载已训练模型"""
    import pickle
    with open(model_path, "rb") as f:
        return pickle.load(f)


def predict_and_rank(model, dataset, segment="test", top_n=10):
    """预测并排名，返回 Top-N 候选"""
    pred = model.predict(dataset, segment=segment)

    if isinstance(pred, pd.Series):
        pred = pred.to_frame("score")

    if pred.index.nlevels == 2:
        last_date = pred.index.get_level_values(0).max()
        latest = pred.loc[last_date].copy()
    else:
        latest = pred.copy()

    latest = latest.sort_values("score", ascending=False)
    candidates = latest.head(top_n)

    return candidates, last_date


def format_candidates(candidates, prediction_date) -> list[dict]:
    """格式化候选股列表"""
    results = []
    for i, (stock_code, row) in enumerate(candidates.iterrows(), 1):
        code = stock_code if isinstance(stock_code, str) else stock_code[0]
        ticker = code.replace("SH", "").replace("SZ", "")
        if code.startswith("SH"):
            ticker_full = f"{ticker}.SH"
        elif code.startswith("SZ"):
            ticker_full = f"{ticker}.SZ"
        else:
            ticker_full = code

        results.append({
            "rank": i,
            "qlib_code": code,
            "ticker": ticker_full,
            "ticker_short": ticker,
            "score": float(row["score"]),
        })
    return results


def run_selection(provider_uri: str, market="csi800", top_n=200, model_path=None):
    """主选股流程"""
    print("=" * 60)
    print("  qlib 量化选股引擎")
    print("=" * 60)

    init_qlib(provider_uri)
    start_date, end_date = get_data_date_range()
    print(f"\n[数据] 日期范围: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
    print(f"[参数] 市场: {market} | Top-N: {top_n}")

    ed = end_date
    total_days = (ed - start_date).days

    test_days = min(60, total_days // 10)
    valid_days = min(60, total_days // 10)

    test_end = ed.strftime("%Y-%m-%d")
    test_start = (ed - timedelta(days=test_days)).strftime("%Y-%m-%d")
    valid_end = (ed - timedelta(days=test_days + 1)).strftime("%Y-%m-%d")
    valid_start = (ed - timedelta(days=test_days + valid_days)).strftime("%Y-%m-%d")
    train_end = (ed - timedelta(days=test_days + valid_days + 1)).strftime("%Y-%m-%d")
    train_start = start_date.strftime("%Y-%m-%d")

    print(f"\n[分段] 训练: {train_start} ~ {train_end}")
    print(f"[分段] 验证: {valid_start} ~ {valid_end}")
    print(f"[分段] 测试: {test_start} ~ {test_end}")

    print("\n[1/3] 构建 Alpha158 数据集...")
    dataset = build_dataset(train_start, train_end, valid_start, valid_end,
                            test_start, test_end, market=market)

    if model_path and Path(model_path).exists():
        print(f"[2/3] 加载已有模型: {model_path}")
        model = load_model(model_path)
    else:
        print("[2/3] 训练 LightGBM 模型...")
        model = train_lgb_model(dataset, model_save_path=model_path)

    print("[3/3] 预测排名中...")
    candidates, pred_date = predict_and_rank(model, dataset, segment="test", top_n=top_n)
    results = format_candidates(candidates, pred_date)

    print(f"\n{'=' * 60}")
    print(f"  预测基准日: {pred_date.strftime('%Y-%m-%d')}")
    print(f"  Top {top_n} 候选股:")
    print(f"{'=' * 60}")
    for r in results:
        print(f"  #{r['rank']:2d}  {r['ticker']:>12s}  预测得分: {r['score']:+.4f}")

    return results, pred_date


if __name__ == "__main__":
    from config import QLIB_DATA_DIR, QLIB_MODEL_DIR

    results, pred_date = run_selection(
        provider_uri=str(QLIB_DATA_DIR),
        market="csi800",
        top_n=200,
        model_path=str(QLIB_MODEL_DIR / "lgb_alpha158.pkl"),
    )

    output_file = Path("output") / f"candidates_{pred_date.strftime('%Y%m%d')}.json"
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "prediction_date": pred_date.strftime("%Y-%m-%d"),
            "market": "csi300",
            "model": "LightGBM_Alpha158",
            "candidates": results,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n[输出] 候选股已保存: {output_file}")
