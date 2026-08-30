"""
run_today.py -- triple-funnel stock selection pipeline
"""
import os
os.environ["PYTHONIOENCODING"] = "utf-8"
import sys
os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["ALL_PROXY"] = ""
os.environ["http_proxy"] = ""
os.environ["https_proxy"] = ""
os.environ["all_proxy"] = ""
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import csv
import json
import subprocess
import sys
import time
import warnings
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

urllib.request.install_opener(
    urllib.request.build_opener(urllib.request.ProxyHandler({}))
)

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from config import QLIB_DATA_DIR, QLIB_MODEL_DIR, OUTPUT_DIR, VENV_PYTHON, UZI_SKILL_DIR


# ══════════════════════════════════════════════════════════════
#  Stage 1: qlib 宽泛初筛
# ══════════════════════════════════════════════════════════════

def stage1_qlib_scan(n=200, market="csi800"):
    """qlib Alpha158 + LightGBM 预测, 取 Top-N"""
    print("\n" + "═" * 70)
    print("  Stage 1/4: qlib 量化初筛 Top-{}  (market={})".format(n, market))
    print("═" * 70)

    from qlib_select import run_selection
    results, pred_date = run_selection(
        provider_uri=str(QLIB_DATA_DIR),
        market=market,
        top_n=n,
        model_path=str(QLIB_MODEL_DIR / "lgb_alpha158.pkl"),
    )
    return results, pred_date


# ══════════════════════════════════════════════════════════════
#  Stage 1.5: 实时行情 + 基础过滤 (涨停/跌停/ST)
# ══════════════════════════════════════════════════════════════

def _safe_float(s, default=0.0):
    try:
        return float(s) if s and s.strip() else default
    except (ValueError, TypeError):
        return default


def fetch_realtime_and_filter(tickers: list[dict]) -> list[dict]:
    """用腾讯 API 获取实时行情, 过滤掉涨停/跌停/ST/停牌"""
    print("\n  [实时行情] 通过腾讯API获取数据...")

    code_map = {}
    qt_codes = []
    for t in tickers:
        short = t["ticker_short"]
        if t["ticker"].endswith(".SH"):
            qt = f"sh{short}"
        else:
            qt = f"sz{short}"
        qt_codes.append(qt)
        code_map[qt] = t

    enriched = []
    batch_size = 30
    for i in range(0, len(qt_codes), batch_size):
        batch = qt_codes[i:i + batch_size]
        url = f"http://qt.gtimg.cn/q={','.join(batch)}"
        try:
            r = urllib.request.urlopen(url, timeout=15)
            data = r.read().decode("gbk")
            for line in data.strip().split(";"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                val = val.strip('"')
                fields = val.split("~")
                if len(fields) < 45:
                    continue

                qt_key = key.split("_")[-1]
                t = code_map.get(qt_key)
                if not t:
                    continue

                name = fields[1]
                price = _safe_float(fields[3])
                change_pct = _safe_float(fields[32])
                pe_ttm = _safe_float(fields[39])

                if price <= 0:
                    continue
                if "ST" in name.upper():
                    continue

                code = t["ticker_short"]
                is_kcb_cyb = code.startswith(("688", "300"))
                limit = 19.5 if is_kcb_cyb else 9.8
                if change_pct >= limit or change_pct <= -limit:
                    continue

                enriched.append({
                    **t,
                    "name": name,
                    "price": price,
                    "prev_close": _safe_float(fields[4]),
                    "open": _safe_float(fields[5]),
                    "change_pct": change_pct,
                    "high": _safe_float(fields[33]),
                    "low": _safe_float(fields[34]),
                    "amount": _safe_float(fields[37]),
                    "turnover_rate": _safe_float(fields[38]),
                    "pe_ttm": pe_ttm,
                    "total_mv": _safe_float(fields[45]) * 10000 if len(fields) > 45 else 0,
                    "volume_ratio": _safe_float(fields[49]) if len(fields) > 49 else 0,
                })
        except Exception as e:
            print(f"  [实时行情] 批次 {i // batch_size + 1} 获取失败: {e}")

    print(f"  [实时行情] 获取 {len(enriched)} 只 (已过滤涨停/跌停/ST/停牌)")
    return enriched


# ══════════════════════════════════════════════════════════════
#  Stage 2: qlib 候选缩窄（不冒充 UZI）
# ══════════════════════════════════════════════════════════════

def stage2_qlib_shortlist(tickers: list[dict], max_stocks: int = 3) -> list[dict]:
    """仅按 qlib 分数缩窄候选；UZI 判断全部留到 deep 阶段。"""
    print("\n" + "═" * 70)
    print(f"  Stage 2/4: qlib 候选缩窄 Top-{max_stocks}（无 UZI 代理分）")
    print("═" * 70)

    ranked = sorted(tickers, key=lambda x: x.get("score", 0), reverse=True)
    return ranked[:max_stocks]


# ══════════════════════════════════════════════════════════════
#  Stage 3: 完整 UZI Deep 分析
# ══════════════════════════════════════════════════════════════

def _generate_portfolio_csv(tickers: list[dict], csv_path: Path):
    """生成 UZI --portfolio 格式的 CSV 文件"""
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "weight", "note"])
        n = len(tickers)
        for t in tickers:
            weight = round(1.0 / n, 4) if n > 0 else 0
            note = f"qlib_rank={t.get('rank', 0)} score={t.get('score', 0):.6f}"
            writer.writerow([t["ticker"], weight, note])


def _parse_uzi_results(tickers: list[dict]) -> list[dict]:
    """从 UZI .cache 目录读取 synthesis.json 结果"""
    cache_dir = UZI_SKILL_DIR / "skills" / "deep-analysis" / "scripts" / ".cache"
    results = []

    for t in tickers:
        ticker = t["ticker"]
        syn_path = cache_dir / ticker / "synthesis.json"
        if not syn_path.exists():
            t["uzi_score"] = None
            t["uzi_verdict"] = "N/A"
            t["uzi_fund_score"] = None
            t["uzi_consensus"] = None
            results.append(t)
            continue

        try:
            syn = json.loads(syn_path.read_text(encoding="utf-8"))
            t["uzi_score"] = syn.get("overall_score")
            t["uzi_verdict"] = syn.get("verdict_label", "N/A")
            t["uzi_fund_score"] = syn.get("fundamental_score")
            t["uzi_consensus"] = syn.get("panel_consensus")
            t["uzi_name"] = syn.get("name", t.get("name", ""))
            t["uzi_verdict_detail"] = syn.get("verdict_detail", "")
        except Exception:
            t["uzi_score"] = None
            t["uzi_verdict"] = "解析失败"

        results.append(t)

    return results


def stage3_uzi_deep_batch(tickers: list[dict], max_stocks: int = 3) -> list[dict]:
    """逐只运行 UZI deep 分析，返回原版 UZI 评分结果。"""
    print("\n" + "═" * 70)
    print(f"  Stage 3/4: UZI Deep 完整分析  ({min(len(tickers), max_stocks)} 只)")
    print("═" * 70)

    batch = tickers[:max_stocks]
    if not batch:
        print("  [UZI Deep] 无候选标的, 跳过")
        return []

    csv_path = OUTPUT_DIR / "uzi_batch_input.csv"
    _generate_portfolio_csv(batch, csv_path)
    print(f"  [UZI Deep] 已生成批量输入: {csv_path}")

    uzi_run_py = UZI_SKILL_DIR / "run.py"
    python_exe = str(VENV_PYTHON)
    cache_dir = UZI_SKILL_DIR / "skills" / "deep-analysis" / "scripts" / ".cache"

    env = os.environ.copy()
    env["UZI_DEPTH"] = "deep"
    env["UZI_CLI_ONLY"] = "1"
    env["UZI_NO_AUTO_OPEN"] = "1"

    t0 = time.time()
    completed = []

    for i, t in enumerate(batch, 1):
        ticker = t["ticker"]
        synthesis_path = cache_dir / ticker / "synthesis.json"
        if synthesis_path.exists():
            synthesis_path.unlink()
        print(f"  [{i}/{len(batch)}] {ticker} ({t.get('name', '')}) — UZI deep 分析中...")
        try:
            result = subprocess.run(
                [python_exe, str(uzi_run_py), ticker,
                 "--depth", "deep", "--no-browser", "--no-resume"],
                cwd=str(UZI_SKILL_DIR),
                env=env,
                capture_output=True,
                timeout=1800,
            )
            if result.returncode != 0:
                stderr_tail = (result.stderr or b"")[-200:].decode("utf-8", errors="replace")
                print(f"    [!] exit={result.returncode}: {stderr_tail}")
            elif synthesis_path.exists():
                completed.append(t)
            else:
                print("    [!] UZI 返回成功但未生成新的 synthesis.json")
        except subprocess.TimeoutExpired:
            print(f"    [!] timeout (1800s), skip")
        except Exception as e:
            print(f"    [!] error: {type(e).__name__}: {str(e)[:100]}")

    dt = int(time.time() - t0)
    print(f"\n  [UZI Deep] 批量分析完成, 耗时 {dt}s")

    results = _parse_uzi_results(completed)

    valid = [r for r in results if r.get("uzi_score") is not None]
    valid.sort(key=lambda x: x["uzi_score"], reverse=True)
    failed = len(results) - len(valid)
    if failed:
        print(f"  [UZI Deep] {failed} 只未获取到分数")

    return valid


# ══════════════════════════════════════════════════════════════
#  Stage 4: 汇总输出
# ══════════════════════════════════════════════════════════════

def stage4_output(results: list[dict], pred_date, stage1_count: int = 0) -> dict:
    """输出最终结果"""
    print("\n" + "═" * 70)
    print("  Stage 4/4: 最终结果汇总")
    print("═" * 70)

    if not results:
        print("  [输出] 今日没有 UZI 认可的标的")
        return {"picks": [], "total": 0}

    print(f"\n  UZI 评分结果 ({len(results)} 只完成分析):")
    print(f"  {'#':>3} {'代码':>10} {'名称':<8} {'现价':>7} {'涨跌%':>7} "
          f"{'UZI分':>6} {'UZI判定':<16}")
    print("  " + "─" * 90)

    for i, r in enumerate(results[:30], 1):
        name = r.get("uzi_name") or r.get("name", "")
        uzi_s = r.get("uzi_score", 0) or 0
        marker = " ★" if uzi_s >= 65 else (" ●" if uzi_s >= 60 else "")
        print(
            f"  {i:>3} {r['ticker']:>10} {name:<8} "
            f"{r.get('price', 0):>7.2f} {r.get('change_pct', 0):>+6.2f}% "
            f"{uzi_s:>5.1f} "
            f"{r.get('uzi_verdict', 'N/A'):<16}{marker}"
        )

    today = datetime.now().strftime("%Y%m%d")
    output_file = OUTPUT_DIR / f"pipeline_result_{today}.json"

    records = []
    for r in results:
        records.append({
            "ticker": r["ticker"],
            "code": r.get("ticker_short", r["ticker"].split(".")[0]),
            "name": r.get("uzi_name") or r.get("name", ""),
            "price": round(r.get("price", 0), 2),
            "change_pct": round(r.get("change_pct", 0), 2),
            "pe_ttm": round(r.get("pe_ttm", 0), 2),
            "qlib_rank": r.get("rank", 0),
            "qlib_score": round(r.get("score", 0), 4),
            "uzi_score": round(r.get("uzi_score", 0) or 0, 1),
            "uzi_verdict": r.get("uzi_verdict", "N/A"),
            "uzi_fund_score": r.get("uzi_fund_score"),
            "uzi_consensus": r.get("uzi_consensus"),
        })

    result_data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "qlib_prediction_date": str(pred_date),
        "pipeline_version": "v6.0_qlib_plus_uzi_deep",
        "stage1_count": stage1_count,
        "deep_analyzed": len(records),
        "uzi_approved_65": len([r for r in records if (r.get("uzi_score") or 0) >= 65]),
        "uzi_watchable_60": len([r for r in records if 60 <= (r.get("uzi_score") or 0) < 65]),
        "picks": records,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    print(f"\n  [输出] 结果已保存: {output_file}")

    approved = [r for r in records if (r.get("uzi_score") or 0) >= 65]
    if approved:
        print(f"\n  ★ UZI 推荐标的 (>=65分):")
        for r in approved:
            print(f"    {r['ticker']} {r['name']} — UZI {r['uzi_score']}分 {r['uzi_verdict']}")

    return result_data


# ══════════════════════════════════════════════════════════════
#  Main Pipeline
# ══════════════════════════════════════════════════════════════

def main():
    t_start = time.time()
    print("+" + "=" * 68 + "+")
    print("|   qlib-UZI 联合选股流水线 v6.0 (原版 UZI Deep)".ljust(68) + "|")
    print("|   " + datetime.now().strftime("%Y-%m-%d %H:%M:%S").ljust(65) + "|")
    print("|   qlib 只做候选排序；最终判断完全交给 UZI Deep".ljust(68) + "|")
    print("+" + "=" * 68 + "+")

    # Stage 1: qlib 宽泛初筛
    candidates, pred_date = stage1_qlib_scan(n=200, market="csi800")
    print(f"\n  → Stage 1 产出: {len(candidates)} 只候选")

    # Stage 1.5: 实时行情 + 基础过滤
    enriched = fetch_realtime_and_filter(candidates)
    print(f"  → 实时行情过滤后: {len(enriched)} 只")

    if not enriched:
        print("  [中止] 无法获取实时行情数据")
        return

    # Stage 2: 仅按 qlib 分数缩窄，避免用简化规则冒充 UZI
    shortlisted = stage2_qlib_shortlist(enriched, max_stocks=3)
    print(f"\n  → Stage 2 产出: {len(shortlisted)} 只 qlib 候选")

    if not shortlisted:
        print("  [中止] 没有可供 UZI Deep 分析的候选")
        return

    # Stage 3: 原版 UZI Deep，强制刷新，禁止复用 Lite 评分
    uzi_results = stage3_uzi_deep_batch(shortlisted, max_stocks=3)
    print(f"\n  → Stage 3 产出: {len(uzi_results)} 只完成 UZI Deep 分析")

    # Stage 4: 汇总输出
    result = stage4_output(uzi_results, pred_date, stage1_count=len(candidates))

    dt = int(time.time() - t_start)
    print(f"\n{'═' * 70}")
    print(f"  流水线完成, 总耗时 {dt // 60}m{dt % 60}s")
    print(f"{'═' * 70}")

    return result


if __name__ == "__main__":
    main()
