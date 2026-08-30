"""
backtest.py — qlib+UZI 代理评分 历史回测

在 5 个历史交易日上回测不同选股策略的未来 5 日收益,
严格避免未来函数: 训练集截止到 T-61, 验证到 T-1, 预测 T 日排名。

策略对比:
  A) qlib top-20 (纯动量)
  B) qlib top-200 → UZI 代理预筛 top-20
  C) qlib top-200 → Stage2 多头 + 低PE 优先
  D) qlib top-200 → 综合因子重排序 top-20

评估指标:
  - T+1 ~ T+5 平均收益
  - 胜率 (正收益占比)
  - 最大/最小个股收益
"""
import os
os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
os.environ["PYTHONIOENCODING"] = "utf-8"

import sys
import json
import pickle
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from config import QLIB_DATA_DIR, QLIB_MODEL_DIR, OUTPUT_DIR


# ══════════════════════════════════════════════════════════════
#  qlib 工具
# ══════════════════════════════════════════════════════════════

_qlib_inited = False

def _init_qlib():
    global _qlib_inited
    if _qlib_inited:
        return
    import qlib
    from qlib.constant import REG_CN
    qlib.init(provider_uri=str(QLIB_DATA_DIR), region=REG_CN)
    _qlib_inited = True


def _get_calendar():
    _init_qlib()
    from qlib.data import D
    return D.calendar(freq="day")


def _get_close_prices(instruments="csi800", start="2025-01-01", end="2026-07-03"):
    """获取收盘价矩阵, 避免未来函数"""
    _init_qlib()
    from qlib.data import D
    inst_list = D.instruments(market=instruments)
    df = D.features(
        instruments=inst_list,
        fields=["$close"],
        start_time=start,
        end_time=end,
        freq="day",
    )
    df.columns = ["close"]
    return df


def _build_dataset_for_date(pred_date, market="csi800"):
    """为特定预测日构建数据集, 严格划分时间窗口"""
    from qlib.contrib.data.handler import Alpha158
    from qlib.utils import init_instance_by_config

    cal = _get_calendar()
    cal_dates = sorted(cal)

    pred_idx = None
    for i, d in enumerate(cal_dates):
        if d.date() >= pred_date.date():
            pred_idx = i
            break
    if pred_idx is None:
        raise ValueError(f"pred_date {pred_date} not in calendar")

    test_end_idx = pred_idx
    test_start_idx = max(0, pred_idx - 1)
    valid_end_idx = test_start_idx - 1
    valid_start_idx = max(0, valid_end_idx - 59)
    train_end_idx = valid_start_idx - 1
    train_start_idx = 0

    fmt = lambda idx: cal_dates[max(0, idx)].strftime("%Y-%m-%d")
    train_s, train_e = fmt(train_start_idx), fmt(train_end_idx)
    valid_s, valid_e = fmt(valid_start_idx), fmt(valid_end_idx)
    test_s, test_e = fmt(test_start_idx), fmt(test_end_idx)

    handler_config = {
        "class": "Alpha158",
        "module_path": "qlib.contrib.data.handler",
        "kwargs": {
            "instruments": market,
            "start_time": train_s,
            "end_time": test_e,
            "fit_start_time": train_s,
            "fit_end_time": train_e,
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
                "train": (train_s, train_e),
                "valid": (valid_s, valid_e),
                "test": (test_s, test_e),
            },
        },
    }
    return init_instance_by_config(dataset_config)


def _build_model(model_type="lgb", d_feat=158):
    """构建不同类型的模型"""
    if model_type == "lgb":
        from qlib.contrib.model.gbdt import LGBModel
        return LGBModel(
            loss="mse", colsample_bytree=0.8879, learning_rate=0.0421,
            subsample=0.8789, lambda_l1=205.6999, lambda_l2=580.9768,
            max_depth=8, num_leaves=210, num_threads=4,
        )
    elif model_type == "densemble":
        from qlib.contrib.model.double_ensemble import DEnsembleModel
        return DEnsembleModel(
            base_model="gbm", loss="mse", num_models=6,
            enable_sr=True, enable_fs=True,
            alpha1=1.0, alpha2=1.0, bins_sr=10, bins_fs=5,
        )
    elif model_type == "gru":
        from qlib.contrib.model.pytorch_gru import GRU
        return GRU(
            d_feat=d_feat, hidden_size=64, num_layers=2,
            dropout=0.0, n_epochs=100, lr=0.001,
            early_stop=10, metric="loss", loss="mse",
            GPU=-1, seed=42,
        )
    elif model_type == "lstm":
        from qlib.contrib.model.pytorch_lstm import LSTM
        return LSTM(
            d_feat=d_feat, hidden_size=64, num_layers=2,
            dropout=0.0, n_epochs=100, lr=0.001,
            early_stop=10, metric="loss", loss="mse",
            GPU=-1, seed=42,
        )
    elif model_type == "linear":
        from qlib.contrib.model.linear import LinearModel
        return LinearModel()
    else:
        raise ValueError(f"Unknown model type: {model_type}")


def _train_and_predict(pred_date, market="csi800", top_n=200, model_type="lgb"):
    """训练模型 + 预测, 返回排名 DataFrame"""
    dataset = _build_dataset_for_date(pred_date, market)

    if model_type in ("gru", "lstm"):
        from qlib.data.dataset.handler import DataHandlerLP
        df_peek = dataset.prepare("train", col_set="feature",
                                  data_key=DataHandlerLP.DK_L)
        actual_d_feat = df_peek.shape[1]
        model = _build_model(model_type, d_feat=actual_d_feat)
    else:
        model = _build_model(model_type)

    model.fit(dataset)

    pred = model.predict(dataset, segment="test")
    if isinstance(pred, pd.Series):
        pred = pred.to_frame("score")

    if pred.index.nlevels == 2:
        last_date = pred.index.get_level_values(0).max()
        latest = pred.loc[last_date].copy()
    else:
        latest = pred.copy()
        last_date = pred_date

    latest = latest.sort_values("score", ascending=False)
    return latest.head(top_n), last_date


def _detect_instrument_level(df):
    """检测 MultiIndex 中哪个 level 是股票代码 (str), 哪个是日期 (Timestamp)"""
    if df.index.nlevels < 2:
        return 0
    v0 = df.index.get_level_values(0)[0]
    return 0 if isinstance(v0, str) else 1


# ══════════════════════════════════════════════════════════════
#  历史 UZI 代理评分 (纯用 qlib 价格数据, 无 API 调用)
# ══════════════════════════════════════════════════════════════

def _compute_stage_from_prices(close_series):
    """从收盘价序列计算均线 Stage (需要 >=60 根K线)"""
    if len(close_series) < 20:
        return "N/A", 5

    closes = close_series.values
    current = closes[-1]
    ma5 = np.mean(closes[-5:])
    ma10 = np.mean(closes[-10:])
    ma20 = np.mean(closes[-20:])
    ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else ma20

    peak = np.max(closes)
    drawdown = (current - peak) / peak * 100 if peak > 0 else 0

    if current > ma5 > ma10 > ma20:
        stage = "Stage2"
        score = 8
    elif current < ma5 < ma10 < ma20:
        stage = "Stage4"
        score = 2
    elif current > ma20 and ma5 < ma10:
        stage = "Stage1"
        score = 6
    else:
        stage = "Stage3"
        score = 3

    if drawdown <= -30:
        score = max(1, score - 1)
    if current > ma5 > ma10 > ma20 > ma60:
        score = min(10, score + 1)

    return stage, score


def _compute_momentum(close_series):
    """计算动量指标"""
    if len(close_series) < 20:
        return 0.0, 0.0, 0.0
    closes = close_series.values
    ret_5d = (closes[-1] / closes[-5] - 1) * 100 if closes[-5] > 0 else 0
    ret_20d = (closes[-1] / closes[-20] - 1) * 100 if closes[-20] > 0 else 0
    vol_20d = np.std(np.diff(np.log(closes[-20:]))) * 100 if len(closes) >= 20 else 0
    return ret_5d, ret_20d, vol_20d


def compute_historical_proxy(all_close, stocks, pred_date, cal_dates):
    """用历史价格计算 UZI 代理评分 (无未来函数)"""
    pred_idx = None
    for i, d in enumerate(cal_dates):
        if d.date() >= pred_date.date():
            pred_idx = i
            break
    if pred_idx is None:
        return {}

    lookback_start = max(0, pred_idx - 119)
    lookback_dates = cal_dates[lookback_start:pred_idx + 1]

    close_level = _detect_instrument_level(all_close)
    close_stocks = set(all_close.index.get_level_values(close_level).unique())

    results = {}
    for stock in stocks:
        try:
            if stock not in close_stocks:
                continue

            stock_data = all_close.xs(stock, level=close_level)
            if isinstance(stock_data, pd.DataFrame):
                stock_data = stock_data["close"]

            mask = stock_data.index.isin(lookback_dates)
            if mask.sum() < 20:
                continue
            prices = stock_data[mask].sort_index()

            stage, stage_score = _compute_stage_from_prices(prices)
            ret_5d, ret_20d, vol_20d = _compute_momentum(prices)

            current_price = float(prices.iloc[-1])
            ma20 = float(prices.iloc[-20:].mean())
            dist_to_ma20 = (current_price - ma20) / ma20 * 100

            results[stock] = {
                "stage": stage,
                "stage_score": stage_score,
                "ret_5d": ret_5d,
                "ret_20d": ret_20d,
                "vol_20d": vol_20d,
                "dist_to_ma20": dist_to_ma20,
                "price": current_price,
            }
        except Exception:
            continue

    return results


def get_forward_returns(all_close, stocks, pred_date, cal_dates, horizons=(1, 2, 3, 5)):
    """计算预测日之后 N 日的收益 (评估用, 不参与选股)"""
    pred_idx = None
    for i, d in enumerate(cal_dates):
        if d.date() >= pred_date.date():
            pred_idx = i
            break
    if pred_idx is None:
        return {}

    close_level = _detect_instrument_level(all_close)
    close_stocks = set(all_close.index.get_level_values(close_level).unique())

    results = {}
    for stock in stocks:
        try:
            if stock not in close_stocks:
                continue
            stock_data = all_close.xs(stock, level=close_level)
            if isinstance(stock_data, pd.DataFrame):
                stock_data = stock_data["close"]

            base_date = cal_dates[pred_idx]
            if base_date not in stock_data.index:
                continue
            base_price = float(stock_data[base_date])

            rets = {}
            for h in horizons:
                fwd_idx = pred_idx + h
                if fwd_idx >= len(cal_dates):
                    continue
                fwd_date = cal_dates[fwd_idx]
                if fwd_date not in stock_data.index:
                    continue
                fwd_price = float(stock_data[fwd_date])
                rets[f"ret_{h}d"] = (fwd_price / base_price - 1) * 100

            if rets:
                results[stock] = rets
        except Exception:
            continue
    return results


# ══════════════════════════════════════════════════════════════
#  策略定义
# ══════════════════════════════════════════════════════════════

def strategy_A_qlib_top(predictions, n=20):
    """策略 A: qlib 纯动量 Top-N"""
    return predictions.head(n).index.tolist()

def strategy_B_proxy_filter(predictions, proxy_data, n=20):
    """策略 B: qlib Top-200 → Stage2/1 + 正动量优先"""
    scored = []
    for stock in predictions.index:
        p = proxy_data.get(stock, {})
        stage_score = p.get("stage_score", 5)
        qlib_score = float(predictions.loc[stock, "score"])

        proxy = stage_score * 4 + 5 * 5 + 5 * 5 + 6 * 4
        scored.append((stock, proxy, qlib_score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [s[0] for s in scored[:n]]


def strategy_C_stage2_lowvol(predictions, proxy_data, n=20):
    """策略 C: 只留 Stage2/Stage1 + 低波动"""
    candidates = []
    for stock in predictions.index:
        p = proxy_data.get(stock, {})
        if p.get("stage") not in ("Stage2", "Stage1"):
            continue
        vol = p.get("vol_20d", 99)
        candidates.append((stock, vol))

    candidates.sort(key=lambda x: x[1])
    selected = [c[0] for c in candidates[:n]]

    if len(selected) < n:
        remaining = [s for s in predictions.index if s not in selected]
        for s in remaining:
            if len(selected) >= n:
                break
            selected.append(s)

    return selected


def strategy_D_composite(predictions, proxy_data, n=20):
    """策略 D: 综合重排序 (qlib分+Stage分+动量+波动)"""
    scored = []
    qlib_scores = predictions["score"]
    q_min, q_max = qlib_scores.min(), qlib_scores.max()
    q_range = q_max - q_min if q_max > q_min else 1

    for stock in predictions.index:
        p = proxy_data.get(stock, {})
        qlib_norm = (float(predictions.loc[stock, "score"]) - q_min) / q_range

        stage_score = p.get("stage_score", 5) / 10.0
        ret_5d = p.get("ret_5d", 0)
        mom_score = min(1, max(0, (ret_5d + 10) / 20))
        vol = p.get("vol_20d", 3)
        vol_score = min(1, max(0, 1 - vol / 6))

        composite = (
            qlib_norm * 0.30 +
            stage_score * 0.30 +
            mom_score * 0.20 +
            vol_score * 0.20
        )
        scored.append((stock, composite))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [s[0] for s in scored[:n]]


def strategy_E_improved(predictions, proxy_data, n=20):
    """策略 E (改进): Stage2 硬过滤 → qlib+趋势质量 综合排序
    核心改进:
      1. Stage2/1 作为硬门槛 (回测证明占87%的Stage2组合收益最佳)
      2. 排除回撤>20%的弱势上涨
      3. qlib得分用于组内排序 (保留qlib的预测能力)
      4. 加入趋势加速度 (5日动量 > 20日动量 = 趋势加速)
    """
    qlib_scores = predictions["score"]
    q_min, q_max = qlib_scores.min(), qlib_scores.max()
    q_range = q_max - q_min if q_max > q_min else 1

    stage2_pool = []
    stage1_pool = []

    for stock in predictions.index:
        p = proxy_data.get(stock, {})
        stage = p.get("stage", "N/A")
        if stage not in ("Stage2", "Stage1"):
            continue

        vol = p.get("vol_20d", 3)
        if vol > 5:
            continue

        dist_ma20 = p.get("dist_to_ma20", 0)
        if dist_ma20 > 15:
            continue

        qlib_norm = (float(predictions.loc[stock, "score"]) - q_min) / q_range

        ret_5d = p.get("ret_5d", 0)
        ret_20d = p.get("ret_20d", 0)
        accel = 1.0 if ret_5d > ret_20d / 4 and ret_5d > -2 else 0.5

        composite = qlib_norm * 0.45 + (p.get("stage_score", 5) / 10.0) * 0.30 + accel * 0.25

        entry = (stock, composite, stage)
        if stage == "Stage2":
            stage2_pool.append(entry)
        else:
            stage1_pool.append(entry)

    stage2_pool.sort(key=lambda x: x[1], reverse=True)
    stage1_pool.sort(key=lambda x: x[1], reverse=True)

    selected = [s[0] for s in stage2_pool[:n]]
    if len(selected) < n:
        for s in stage1_pool:
            if len(selected) >= n:
                break
            selected.append(s[0])

    if len(selected) < n:
        remaining = [s for s in predictions.index if s not in set(selected)]
        for s in remaining[:n - len(selected)]:
            selected.append(s)

    return selected


# ══════════════════════════════════════════════════════════════
#  单日回测
# ══════════════════════════════════════════════════════════════

def strategy_F_pure_uzi(all_proxy, n=20):
    """策略 F: 纯 UZI 代理评分 (不依赖 qlib, 全市场 Stage2 + 趋势质量)"""
    stage2 = []
    stage1 = []
    for stock, p in all_proxy.items():
        stage = p.get("stage", "N/A")
        if stage not in ("Stage2", "Stage1"):
            continue
        vol = p.get("vol_20d", 99)
        if vol > 5:
            continue
        dist = p.get("dist_to_ma20", 0)
        if dist > 15:
            continue

        ret_5d = p.get("ret_5d", 0)
        ret_20d = p.get("ret_20d", 0)
        accel = 1.0 if ret_5d > ret_20d / 4 and ret_5d > -2 else 0.5

        score = (p.get("stage_score", 5) / 10.0) * 0.40 + accel * 0.30
        mom_q = min(1, max(0, (ret_5d + 5) / 15))
        score += mom_q * 0.15
        vol_q = min(1, max(0, 1 - vol / 5))
        score += vol_q * 0.15

        if stage == "Stage2":
            stage2.append((stock, score))
        else:
            stage1.append((stock, score))

    stage2.sort(key=lambda x: x[1], reverse=True)
    stage1.sort(key=lambda x: x[1], reverse=True)

    selected = [s[0] for s in stage2[:n]]
    if len(selected) < n:
        for s in stage1:
            if len(selected) >= n:
                break
            selected.append(s[0])
    return selected


def strategy_G_strict_risk(predictions, proxy_data, n=20):
    """策略 G: qlib + Stage2 + 严格风控
    - vol_20d < 3.5 (低波动)
    - dist_to_ma20 在 [-5%, +12%] (不追高、不抄底)
    - ret_5d > -1% (短期不破位)
    - 组内按 qlib 分排序
    """
    qlib_scores = predictions["score"]
    q_min, q_max = qlib_scores.min(), qlib_scores.max()
    q_range = q_max - q_min if q_max > q_min else 1

    pool = []
    for stock in predictions.index:
        p = proxy_data.get(stock, {})
        if p.get("stage", "N/A") != "Stage2":
            continue
        vol = p.get("vol_20d", 99)
        if vol > 3.5:
            continue
        dist = p.get("dist_to_ma20", 99)
        if dist < -5 or dist > 12:
            continue
        ret5 = p.get("ret_5d", -99)
        if ret5 < -1:
            continue

        qlib_norm = (float(predictions.loc[stock, "score"]) - q_min) / q_range
        pool.append((stock, qlib_norm))

    pool.sort(key=lambda x: x[1], reverse=True)
    selected = [s[0] for s in pool[:n]]

    if len(selected) < n:
        for stock in predictions.index:
            if stock in set(selected):
                continue
            p = proxy_data.get(stock, {})
            if p.get("stage") in ("Stage2", "Stage1") and p.get("vol_20d", 99) < 5:
                selected.append(stock)
                if len(selected) >= n:
                    break

    return selected


def strategy_H_intersection(predictions, proxy_data, all_proxy, n=20):
    """策略 H: qlib ∩ UZI 交集 — 只选两个系统都看好的股票
    - qlib Top-100 与全市场 UZI-Stage2 Top-100 的交集
    - 用 (qlib_rank_norm + uzi_score_norm) 排序
    """
    qlib_top = set(predictions.head(100).index.tolist())

    uzi_scored = []
    for stock, p in all_proxy.items():
        if p.get("stage") != "Stage2":
            continue
        vol = p.get("vol_20d", 99)
        if vol > 5:
            continue
        ret_5d = p.get("ret_5d", 0)
        ret_20d = p.get("ret_20d", 0)
        score = (p.get("stage_score", 5) / 10.0) * 0.4
        accel = 1.0 if ret_5d > ret_20d / 4 and ret_5d > -2 else 0.5
        score += accel * 0.3
        mom_q = min(1, max(0, (ret_5d + 5) / 15))
        score += mom_q * 0.15
        vol_q = min(1, max(0, 1 - vol / 5))
        score += vol_q * 0.15
        uzi_scored.append((stock, score))

    uzi_scored.sort(key=lambda x: x[1], reverse=True)
    uzi_top = {s[0]: rank for rank, (s, _) in enumerate(
        [(s, sc) for s, sc in uzi_scored[:100]])}

    intersection = qlib_top & set(uzi_top.keys())

    if not intersection:
        qlib_top150 = set(predictions.head(150).index.tolist())
        uzi_top150 = {s[0] for s in uzi_scored[:150]}
        intersection = qlib_top150 & uzi_top150

    qlib_scores = predictions["score"]
    q_min, q_max = qlib_scores.min(), qlib_scores.max()
    q_range = q_max - q_min if q_max > q_min else 1

    ranked = []
    for stock in intersection:
        qlib_norm = (float(predictions.loc[stock, "score"]) - q_min) / q_range if stock in predictions.index else 0
        uzi_rank = uzi_top.get(stock, 100)
        uzi_norm = 1 - uzi_rank / 100
        combined = qlib_norm * 0.5 + uzi_norm * 0.5
        ranked.append((stock, combined))

    ranked.sort(key=lambda x: x[1], reverse=True)
    selected = [s[0] for s in ranked[:n]]

    if len(selected) < n:
        for s, _ in uzi_scored:
            if s not in set(selected):
                selected.append(s)
                if len(selected) >= n:
                    break

    return selected


def strategy_I_adaptive(predictions, proxy_data, all_proxy, n=20):
    """策略 I: 市场自适应 — 根据 Stage2 占比动态调权
    - Stage2 占比高 (>30%): 行情好, 加大 qlib 权重 (选最强)
    - Stage2 占比低 (<15%): 行情差, 加大风控权重 (选最稳)
    """
    total = len(all_proxy)
    stage2_count = sum(1 for p in all_proxy.values() if p.get("stage") == "Stage2")
    stage2_pct = stage2_count / total * 100 if total > 0 else 0

    if stage2_pct > 30:
        w_qlib, w_stage, w_mom, w_vol = 0.50, 0.20, 0.20, 0.10
        vol_limit, dist_limit = 5, 18
    elif stage2_pct > 15:
        w_qlib, w_stage, w_mom, w_vol = 0.35, 0.25, 0.20, 0.20
        vol_limit, dist_limit = 4.5, 15
    else:
        w_qlib, w_stage, w_mom, w_vol = 0.20, 0.25, 0.20, 0.35
        vol_limit, dist_limit = 3.5, 12

    qlib_scores = predictions["score"]
    q_min, q_max = qlib_scores.min(), qlib_scores.max()
    q_range = q_max - q_min if q_max > q_min else 1

    pool = []
    for stock in predictions.index:
        p = proxy_data.get(stock, {})
        stage = p.get("stage", "N/A")
        if stage not in ("Stage2", "Stage1"):
            continue
        vol = p.get("vol_20d", 99)
        if vol > vol_limit:
            continue
        dist = p.get("dist_to_ma20", 99)
        if dist > dist_limit:
            continue

        qlib_norm = (float(predictions.loc[stock, "score"]) - q_min) / q_range
        stage_norm = p.get("stage_score", 5) / 10.0
        ret_5d = p.get("ret_5d", 0)
        mom = min(1, max(0, (ret_5d + 5) / 15))
        vol_norm = min(1, max(0, 1 - vol / vol_limit))

        score = w_qlib * qlib_norm + w_stage * stage_norm + w_mom * mom + w_vol * vol_norm
        if stage == "Stage2":
            score += 0.05
        pool.append((stock, score))

    pool.sort(key=lambda x: x[1], reverse=True)
    selected = [s[0] for s in pool[:n]]

    if len(selected) < n:
        remaining = [s for s in predictions.index if s not in set(selected)]
        for s in remaining[:n - len(selected)]:
            selected.append(s)

    return selected


def strategy_J_fusion(predictions, proxy_data, all_proxy, n=20):
    """策略 J: 双模自适应 (10 日全样本优化)

    10日回测数据:
      Stage2>=15% (5日): G=+1.42%, A=+0.54% → G 压倒性领先
      Stage2<15%  (5日): A=+0.00%, G=+0.19% → G 仍然略优
      但 Stage2<10% (2日): A=(-0.31%), G=(-1.80%) → A 明显更好

    最优切换点: Stage2=12%
      >=12%: G 模式 (Stage2+风控, 覆盖所有正常和牛市)
      <12%:  A 模式 (纯 qlib 动量, 捕获熊市反弹)
    """
    total = len(all_proxy)
    s2_count = sum(1 for p in all_proxy.values() if p.get("stage") == "Stage2")
    s2_pct = s2_count / total * 100 if total > 0 else 0

    if s2_pct < 12:
        return predictions.head(n).index.tolist()

    qlib_scores = predictions["score"]
    q_min, q_max = qlib_scores.min(), qlib_scores.max()
    q_range = q_max - q_min if q_max > q_min else 1

    pool = []
    for stock in predictions.index:
        p = proxy_data.get(stock, {})
        stage = p.get("stage", "N/A")
        if stage not in ("Stage2", "Stage1"):
            continue
        vol = p.get("vol_20d", 99)
        if vol > 4:
            continue
        dist = p.get("dist_to_ma20", 99)
        if dist < -5 or dist > 15:
            continue
        ret5 = p.get("ret_5d", -99)
        if ret5 < -1:
            continue

        qlib_norm = (float(predictions.loc[stock, "score"]) - q_min) / q_range
        pool.append((stock, qlib_norm))

    pool.sort(key=lambda x: x[1], reverse=True)
    selected = [s[0] for s in pool[:n]]

    if len(selected) < n:
        for stock in predictions.index:
            if stock in set(selected):
                continue
            p = proxy_data.get(stock, {})
            if p.get("stage") in ("Stage2", "Stage1") and p.get("vol_20d", 99) < 5:
                selected.append(stock)
                if len(selected) >= n:
                    break

    if len(selected) < n:
        remaining = [s for s in predictions.index if s not in set(selected)]
        for s in remaining[:n - len(selected)]:
            selected.append(s)

    return selected


def backtest_one_day(pred_date, all_close, cal_dates, market="csi800",
                     model_type="lgb"):
    """对单个交易日进行回测"""
    date_str = pred_date.strftime("%Y-%m-%d")
    print(f"\n{'='*70}")
    print(f"  回测日: {date_str}  模型: {model_type}")
    print(f"{'='*70}")

    print(f"  [1/5] 训练 {model_type} 模型 + 预测...")
    predictions, actual_date = _train_and_predict(
        pred_date, market=market, top_n=200, model_type=model_type)
    print(f"    qlib 预测基准日: {actual_date}")

    stocks = predictions.index.tolist()
    print(f"  [2/5] 计算 qlib Top-200 代理评分...")
    proxy = compute_historical_proxy(all_close, stocks, pred_date, cal_dates)
    print(f"    代理评分覆盖: {len(proxy)}/{len(stocks)}")

    # 全市场代理评分 (给纯 UZI 策略用)
    close_level = _detect_instrument_level(all_close)
    all_stocks_in_data = list(all_close.index.get_level_values(close_level).unique())
    print(f"  [3/5] 计算全市场代理评分 ({len(all_stocks_in_data)} 只)...")
    all_proxy = compute_historical_proxy(all_close, all_stocks_in_data, pred_date, cal_dates)
    print(f"    全市场代理覆盖: {len(all_proxy)}")

    # 未来收益: 需要覆盖 qlib picks + pure UZI picks
    pure_uzi_picks = strategy_F_pure_uzi(all_proxy, 20)
    all_eval_stocks = list(set(stocks + pure_uzi_picks))
    print(f"  [4/5] 计算未来收益 ({len(all_eval_stocks)} 只)...")
    fwd = get_forward_returns(all_close, all_eval_stocks, pred_date, cal_dates)
    print(f"    未来收益覆盖: {len(fwd)}/{len(all_eval_stocks)}")

    # 市场状态
    total_mkt = len(all_proxy)
    s2_mkt = sum(1 for p in all_proxy.values() if p.get("stage") == "Stage2")
    s2_pct = s2_mkt / total_mkt * 100 if total_mkt > 0 else 0
    print(f"    市场 Stage2 占比: {s2_pct:.1f}% ({s2_mkt}/{total_mkt})")

    print(f"  [5/5] 评估各策略...")
    strategies = {
        "A_qlib_top20": strategy_A_qlib_top(predictions, 20),
        "B_proxy_filter": strategy_B_proxy_filter(predictions, proxy, 20),
        "F_pure_uzi": pure_uzi_picks,
        "G_strict_risk": strategy_G_strict_risk(predictions, proxy, 20),
        "J_fusion": strategy_J_fusion(predictions, proxy, all_proxy, 20),
    }

    results = {}
    for name, picks in strategies.items():
        rets_5d = []
        for s in picks:
            r = fwd.get(s, {})
            if "ret_5d" in r:
                rets_5d.append(r["ret_5d"])

        if rets_5d:
            avg = np.mean(rets_5d)
            winrate = sum(1 for r in rets_5d if r > 0) / len(rets_5d) * 100
            max_r = max(rets_5d)
            min_r = min(rets_5d)
        else:
            avg = winrate = max_r = min_r = 0

        stage_dist = {}
        for s in picks:
            st = all_proxy.get(s, proxy.get(s, {})).get("stage", "N/A")
            stage_dist[st] = stage_dist.get(st, 0) + 1

        results[name] = {
            "n_picks": len(picks),
            "n_with_return": len(rets_5d),
            "avg_ret_5d": round(avg, 3),
            "win_rate": round(winrate, 1),
            "max_ret_5d": round(max_r, 3),
            "min_ret_5d": round(min_r, 3),
            "stage_dist": stage_dist,
        }

        print(f"    {name:20s}: avg_5d={avg:+.2f}%  winrate={winrate:.0f}%  "
              f"max={max_r:+.2f}%  min={min_r:+.2f}%  stages={stage_dist}")

    return {
        "date": date_str,
        "actual_pred_date": str(actual_date),
        "n_predictions": len(predictions),
        "n_proxy": len(proxy),
        "n_forward": len(fwd),
        "strategies": results,
    }


# ══════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════

def main():
    print("="*70)
    print("  多模型横评回测: LightGBM vs DoubleEnsemble")
    print("  3 个交易日 × 2 种模型, 对比 qlib Top-20 的样本外收益")
    print("="*70)

    test_dates = [
        datetime(2025, 10, 24),
        datetime(2026, 1, 16),
        datetime(2026, 5, 16),
    ]

    model_types = ["lgb", "densemble"]

    _init_qlib()
    cal = _get_calendar()
    cal_dates = sorted(cal)

    snapped = []
    for td in test_dates:
        best = None
        for d in cal_dates:
            if d.date() >= td.date():
                best = d
                break
        if best:
            snapped.append(best)
    test_dates = snapped
    print(f"\n  实际测试日: {[d.strftime('%Y-%m-%d') for d in test_dates]}")

    print("\n  预加载收盘价数据...")
    all_close = _get_close_prices(
        instruments="csi800",
        start="2024-06-01",
        end="2026-07-03",
    )
    print(f"  收盘价: {all_close.shape[0]} 行")

    model_results = {m: [] for m in model_types}

    for td in test_dates:
        for mt in model_types:
            try:
                r = backtest_one_day(td, all_close, cal_dates,
                                     market="csi800", model_type=mt)
                r["model"] = mt
                model_results[mt].append(r)
            except Exception as e:
                print(f"\n  [!] {td.strftime('%Y-%m-%d')} {mt} 回测失败: "
                      f"{type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()

    # 汇总: 每个模型 × 每个策略的平均收益
    print("\n" + "="*70)
    print("  多模型回测汇总")
    print("="*70)

    strategy_names = ["A_qlib_top20", "B_proxy_filter", "G_strict_risk", "J_fusion"]

    for mt in model_types:
        results = model_results[mt]
        if not results:
            print(f"\n  [{mt}] 无结果")
            continue

        print(f"\n  ── {mt.upper()} {'─'*50}")
        header = f"  {'策略':<20s}"
        for r in results:
            header += f"  {r['date'][5:]:>8s}"
        header += "    平均"
        print(header)
        print("  " + "-" * (len(header) - 2))

        for sn in strategy_names:
            line = f"  {sn:<20s}"
            vals = []
            for r in results:
                v = r["strategies"].get(sn, {}).get("avg_ret_5d", 0)
                line += f"  {v:+7.2f}%"
                vals.append(v)
            avg = np.mean(vals) if vals else 0
            line += f"  {avg:+7.2f}%"
            print(line)

        for sn in strategy_names:
            wrs = [r["strategies"].get(sn, {}).get("win_rate", 0) for r in results]
            avg_wr = np.mean(wrs)
            print(f"  {sn:<20s} 平均胜率: {avg_wr:.1f}%")

    # 模型间对比: A_qlib_top20 (纯模型能力对比)
    print(f"\n{'='*70}")
    print("  纯模型能力对比 (A_qlib_top20 策略)")
    print(f"{'='*70}")
    print(f"  {'模型':<15s}  {'5日均收益':>10s}  {'平均胜率':>10s}")
    print(f"  {'-'*40}")
    for mt in model_types:
        results = model_results[mt]
        if not results:
            continue
        rets = [r["strategies"].get("A_qlib_top20", {}).get("avg_ret_5d", 0)
                for r in results]
        wrs = [r["strategies"].get("A_qlib_top20", {}).get("win_rate", 0)
               for r in results]
        print(f"  {mt:<15s}  {np.mean(rets):+8.2f}%  {np.mean(wrs):>8.1f}%")

    out = OUTPUT_DIR / "backtest_model_compare.json"
    all_data = []
    for mt in model_types:
        all_data.extend(model_results[mt])
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  结果已保存: {out}")


if __name__ == "__main__":
    main()
