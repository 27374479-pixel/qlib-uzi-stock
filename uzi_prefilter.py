"""
uzi_prefilter.py — UZI 代理评分预筛模块

模拟 UZI score_dimensions 加权评分逻辑，快速筛掉 UZI 不会看好的标的。
优先使用腾讯行情 (HTTP, 100% 可靠) 数据，Eastmoney 数据为可选增强。
"""
import json
import re
import time
import urllib.request
from typing import Optional


def _safe_float(v, default=0.0) -> float:
    try:
        if v is None or v == "" or v == "--" or v == "-":
            return default
        return float(str(v).replace(",", "").replace("%", "").replace("+", ""))
    except (ValueError, TypeError):
        return default


def _http_get(url: str, timeout: int = 15, retries: int = 2) -> Optional[bytes]:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://quote.eastmoney.com/",
            })
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.read()
        except Exception:
            if attempt < retries - 1:
                time.sleep(1 + attempt)
    return None


def _em_json(url: str, timeout: int = 15) -> Optional[dict]:
    raw = _http_get(url, timeout)
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    m = re.search(r'jQuery\d*\((.*)\)\s*;?\s*$', text, re.S)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        return json.loads(text[start:end])
    return None


# ═══════════════════════════════════════════════════════════════
#  数据获取: 腾讯K线 + 东方财富资金流 (最可靠的组合)
# ═══════════════════════════════════════════════════════════════

def _ticker_to_tencent(ticker: str) -> str:
    short = ticker.split(".")[0]
    suffix = ticker.split(".")[-1].upper() if "." in ticker else ""
    if suffix == "SH" or short.startswith(("6", "9")):
        return f"sh{short}"
    return f"sz{short}"


def _ticker_to_em_secid(ticker: str) -> str:
    short = ticker.split(".")[0]
    suffix = ticker.split(".")[-1].upper() if "." in ticker else ""
    if suffix == "SH" or short.startswith(("6", "9")):
        return f"1.{short}"
    return f"0.{short}"


def fetch_kline_stage(ticker: str) -> dict:
    """获取K线计算均线 Stage (优先 Eastmoney, 回退腾讯)"""
    closes = []

    secid = _ticker_to_em_secid(ticker)
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        f"cb=jQuery112&secid={secid}&klt=101&fqt=1"
        f"&fields1=f1,f2,f3,f4,f5,f6,f7,f8"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59"
        f"&beg=0&end=20500101&lmt=120"
        f"&ut=fa5fd1943c7b386f172d6893dbfba10b"
    )
    data = _em_json(url)
    if data:
        klines = (data.get("data") or {}).get("klines") or []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 3:
                closes.append(_safe_float(parts[2]))

    if len(closes) < 20:
        qt = _ticker_to_tencent(ticker)
        url2 = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={qt},day,,120,qfq"
        raw = _http_get(url2)
        if raw:
            try:
                jd = json.loads(raw.decode("utf-8"))
                qfq_data = (jd.get("data") or {}).get(qt, {})
                days = qfq_data.get("qfqday") or qfq_data.get("day") or []
                if isinstance(days, list) and len(days) >= 20:
                    closes = [float(d[2]) for d in days if isinstance(d, list) and len(d) >= 3]
            except Exception:
                pass

    if len(closes) < 20:
        return {}

    current = closes[-1]
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20

    peak = max(closes)
    drawdown = (current - peak) / peak * 100 if peak > 0 else 0

    if current > ma5 > ma10 > ma20:
        stage, ma_align = "Stage 2", "多头排列"
    elif current < ma5 < ma10 < ma20:
        stage, ma_align = "Stage 4", "空头排列"
    elif current > ma20 and ma5 < ma10:
        stage, ma_align = "Stage 1", "底部整理"
    else:
        stage, ma_align = "Stage 3", "顶部整理"

    return {"stage": stage, "ma_align": ma_align, "drawdown": drawdown, "_closes": closes}


def fetch_capital_flow_5d(ticker: str) -> float:
    """获取5日主力净流入合计"""
    secid = _ticker_to_em_secid(ticker)
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?"
        f"cb=jQuery112&secid={secid}&lmt=5&klt=101"
        f"&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57"
        f"&ut=fa5fd1943c7b386f172d6893dbfba10b"
    )
    data = _em_json(url)
    if not data:
        return 0.0
    klines = (data.get("data") or {}).get("klines") or []
    total = 0.0
    for line in klines[-5:]:
        parts = line.split(",")
        if len(parts) >= 2:
            total += _safe_float(parts[1])
    return total


def fetch_roe_batch(tickers: list[dict]) -> dict[str, float]:
    """尝试从 Eastmoney 列表 API 批量获取 ROE, 失败则返回空"""
    results = {}
    ut = "fa5fd1943c7b386f172d6893dbfba10b"

    for page in range(1, 20):
        url = (
            f"https://push2.eastmoney.com/api/qt/clist/get?"
            f"cb=jQuery112&fid=f12&po=0&pz=500&pn={page}&np=1&fltt=2"
            f"&fields=f12,f37"
            f"&fs=m:0+t:6+f:!2,m:1+t:2+f:!2"
            f"&ut={ut}"
        )
        data = _em_json(url)
        if not data:
            break
        diffs = (data.get("data") or {}).get("diff") or []
        if isinstance(diffs, dict):
            diffs = list(diffs.values())
        if not diffs:
            break
        for item in diffs:
            code = str(item.get("f12", ""))
            roe = _safe_float(item.get("f37"))
            if code and roe != 0:
                results[code] = roe
        total = (data.get("data") or {}).get("total", 0)
        if page * 500 >= total:
            break
        time.sleep(0.3)

    return results


# ═══════════════════════════════════════════════════════════════
#  UZI 评分模拟
# ═══════════════════════════════════════════════════════════════

def score_dim1(roe: float, growth_yoy: float = 0, debt: float = 45) -> int:
    score = 5
    if roe >= 15: score += 2
    elif roe >= 10: score += 1
    elif roe < 5 and roe != 0: score -= 2
    if growth_yoy >= 20: score += 1
    if debt >= 60: score -= 1
    return max(1, min(10, score))


def score_dim2(kline: dict) -> int:
    score = 5
    stage = kline.get("stage", "")
    ma_align = kline.get("ma_align", "")
    dd = kline.get("drawdown", 0)
    if "Stage 2" in stage: score += 2
    elif "Stage 1" in stage: score += 1
    elif "Stage 3" in stage or "Stage 4" in stage: score -= 2
    if "多头" in ma_align: score += 1
    if dd <= -30: score -= 1
    return max(1, min(10, score))


def score_dim10(pe_ttm: float) -> int:
    if pe_ttm <= 0 or pe_ttm > 2000:
        return 5
    if pe_ttm < 15: return 9
    elif pe_ttm < 25: return 7
    elif pe_ttm < 40: return 5
    elif pe_ttm < 60: return 3
    return 2


def score_dim12(main_net_5d: float) -> int:
    score = 6  # 默认含无解禁 +1
    if main_net_5d > 0: score += 2
    elif main_net_5d < 0: score -= 1
    return max(1, min(10, score))


_DEFAULT_DIMS = {
    "3_macro": (6, 3), "4_peers": (6, 4), "5_chain": (6, 4),
    "6_research": (6, 3), "7_industry": (7, 4), "8_materials": (6, 3),
    "9_futures": (5, 2), "11_governance": (7, 4), "13_policy": (6, 3),
    "14_moat": (6, 3), "15_events": (6, 4), "16_lhb": (5, 4),
    "17_sentiment": (6, 3), "18_trap": (9, 5), "19_contests": (5, 4),
}
_DEFAULT_WEIGHTED = sum(s * w for s, w in _DEFAULT_DIMS.values())
_DEFAULT_WEIGHT_SUM = sum(w for _, w in _DEFAULT_DIMS.values())


def compute_proxy_score(d1: int, d2: int, d10: int, d12: int) -> float:
    active = d1 * 5 + d2 * 4 + d10 * 5 + d12 * 4
    total = active + _DEFAULT_WEIGHTED
    weight = 18 + _DEFAULT_WEIGHT_SUM
    return round(total / weight * 10, 1)


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

def _compute_kline_extras(kline: dict, closes: list) -> dict:
    """从K线数据计算波动率、动量等风控指标"""
    extras = {"vol_20d": 99.0, "ret_5d": 0.0, "ret_20d": 0.0, "dist_to_ma20": 0.0}
    if not closes or len(closes) < 20:
        return extras
    import math
    log_rets = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes))
                if closes[i-1] > 0 and closes[i] > 0]
    if len(log_rets) >= 19:
        extras["vol_20d"] = (sum(r**2 for r in log_rets[-19:]) / 19) ** 0.5 * 100
    if closes[-5] > 0:
        extras["ret_5d"] = (closes[-1] / closes[-5] - 1) * 100
    if closes[-20] > 0:
        extras["ret_20d"] = (closes[-1] / closes[-20] - 1) * 100
    ma20 = sum(closes[-20:]) / 20
    if ma20 > 0:
        extras["dist_to_ma20"] = (closes[-1] - ma20) / ma20 * 100
    return extras


def run_prefilter(tickers: list[dict], threshold: float = 58.0) -> list[dict]:
    """
    回测优化版 v5.0 — 双模自适应 (10日全样本验证)

    10日回测结论 (2轮 x 5交易日, 覆盖牛熊市):
      Stage2>=12%时: G策略(Stage2硬过滤+风控) avg+1.42% >> A(纯qlib) +0.54%
      Stage2<12%时:  A策略(纯qlib动量) avg+1.22% >> G(Stage2过滤) -1.80%

    自适应逻辑: 检测当前市场Stage2占比, 动态切换选股模式
      >= 12%: G模式 (Stage2+Stage1过滤, vol<4, MA距离<15, ret5>-1, qlib排序)
      <  12%: A模式 (不做Stage过滤, 直接按qlib分数排序, 捕获熊市反弹)
    """
    if not tickers:
        return []

    # Phase 1: 尝试批量获取 ROE (可能因限流失败)
    print("\n  [代理评分] 尝试获取 ROE 数据...")
    roe_map = fetch_roe_batch(tickers)
    roe_hit = sum(1 for t in tickers if t["ticker_short"] in roe_map)
    print(f"  [代理评分] ROE 命中: {roe_hit}/{len(tickers)} (API限流时退化为默认值)")

    # Phase 2: dim1 + dim10 粗筛 (仅用已有数据)
    pre_results = []
    for t in tickers:
        short = t["ticker_short"]
        pe = t.get("pe_ttm", 0)
        roe = roe_map.get(short, 0)

        d1 = score_dim1(roe)
        d10 = score_dim10(pe)

        rough = compute_proxy_score(d1, 5, d10, 6)
        if rough < threshold - 4:
            continue

        pre_results.append({
            **t,
            "fin_roe": roe,
            "dim1_financials": d1,
            "dim10_valuation": d10,
        })

    print(f"  [代理评分] 粗筛通过: {len(pre_results)} / {len(tickers)} 只")
    if not pre_results:
        return []

    # Phase 3: K线 + 资金流 → 完整 proxy score + 风控指标
    print(f"  [代理评分] 获取K线+资金流 ({len(pre_results)} 只)...")
    all_scored = []
    stage_counts = {"Stage 1": 0, "Stage 2": 0, "Stage 3": 0, "Stage 4": 0, "N/A": 0}

    for i, t in enumerate(pre_results):
        kline = fetch_kline_stage(t["ticker"])
        d2 = score_dim2(kline)

        cap_5d = fetch_capital_flow_5d(t["ticker"])
        d12 = score_dim12(cap_5d)

        proxy = compute_proxy_score(t["dim1_financials"], d2, t["dim10_valuation"], d12)

        extras = _compute_kline_extras(kline, kline.get("_closes", []))

        entry = {**t}
        entry["dim2_kline"] = d2
        entry["dim12_capital"] = d12
        entry["kline_stage"] = kline.get("stage", "N/A")
        entry["cap_net_5d"] = cap_5d
        entry["proxy_score"] = proxy
        entry["vol_20d"] = extras["vol_20d"]
        entry["ret_5d"] = extras["ret_5d"]
        entry["ret_20d"] = extras["ret_20d"]
        entry["dist_to_ma20"] = extras["dist_to_ma20"]

        stage_key = kline.get("stage", "N/A")
        stage_counts[stage_key] = stage_counts.get(stage_key, 0) + 1
        all_scored.append(entry)

        if (i + 1) % 20 == 0:
            print(f"    ...已处理 {i + 1}/{len(pre_results)}")
        time.sleep(0.15)

    print(f"\n  [代理评分] Stage 分布: {stage_counts}")

    # Phase 4: 市场状态检测 + 双模自适应 (10 日全样本验证 v5.0)
    total_scored = len(all_scored)
    s2_count = sum(1 for e in all_scored if "Stage 2" in e.get("kline_stage", ""))
    s2_pct = s2_count / total_scored * 100 if total_scored > 0 else 0
    print(f"  [代理评分] 市场 Stage2 占比: {s2_pct:.1f}% ({s2_count}/{total_scored})")

    if s2_pct < 12:
        # A 模式: Stage2 极少 → 纯 qlib 动量排序 (10日回测: Stage2<12%时 A 优于 G)
        print(f"  [代理评分] 切换 A 模式 (Stage2<12%, 纯 qlib 动量排序)")
        results = sorted(all_scored, key=lambda x: x.get("score", 0), reverse=True)
        print(f"  [代理评分] 最终产出: {len(results)} 只 (A 模式, 按 qlib 分数排序)")
        return results

    # G 模式: Stage2 充足 → Stage2 硬过滤 + 风控 + qlib 排序
    print(f"  [代理评分] 切换 G 模式 (Stage2>={12}%, Stage2 过滤 + 风控)")
    strict_pool = []
    relaxed_pool = []
    fallback = []

    for entry in all_scored:
        stage = entry["kline_stage"]
        vol = entry.get("vol_20d", 99)
        dist = entry.get("dist_to_ma20", 0)
        ret5 = entry.get("ret_5d", -99)

        if "Stage 2" in stage and vol <= 4.0 and -5 <= dist <= 15 and ret5 > -1:
            strict_pool.append(entry)
        elif "Stage 2" in stage and vol <= 5.0:
            relaxed_pool.append(entry)
        elif "Stage 1" in stage and vol <= 5.0:
            relaxed_pool.append(entry)
        elif entry["proxy_score"] >= threshold:
            fallback.append(entry)

    qlib_scores = [t.get("score", 0) for t in all_scored]
    q_min = min(qlib_scores) if qlib_scores else 0
    q_max = max(qlib_scores) if qlib_scores else 1
    q_range = q_max - q_min if q_max > q_min else 1

    def _qlib_key(t):
        return (t.get("score", 0) - q_min) / q_range

    strict_pool.sort(key=_qlib_key, reverse=True)
    relaxed_pool.sort(key=_qlib_key, reverse=True)
    fallback.sort(key=lambda x: x["proxy_score"], reverse=True)

    results = strict_pool + relaxed_pool + fallback

    s_strict = len(strict_pool)
    s_relaxed = len(relaxed_pool)
    fb = len(fallback)
    print(f"  [代理评分] 严格池(Stage2+风控)={s_strict}, "
          f"宽松池(Stage2/1)={s_relaxed}, 回退={fb}")
    print(f"  [代理评分] 最终产出: {len(results)} 只 (G 模式)")
    return results
