"""
run_pipeline.py — qlib 选股 → UZI 深度分析 完整工作流

用法:
  python run_pipeline.py                    # 默认: csi300 Top-5
  python run_pipeline.py --market csi500 --top 10
  python run_pipeline.py --skip-qlib --tickers 600519 000858  # 直接指定股票
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import (
    PROJECT_ROOT,
    VENV_PYTHON,
    QLIB_DATA_DIR,
    QLIB_MODEL_DIR,
    UZI_SKILL_DIR,
    OUTPUT_DIR,
)


def run_qlib_selection(market="csi300", top_n=5):
    """运行 qlib 选股"""
    from qlib_select import run_selection

    results, pred_date = run_selection(
        provider_uri=str(QLIB_DATA_DIR),
        market=market,
        top_n=top_n,
        model_path=str(QLIB_MODEL_DIR / "lgb_alpha158.pkl"),
    )

    output_file = OUTPUT_DIR / f"candidates_{pred_date.strftime('%Y%m%d')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "pipeline_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "prediction_date": pred_date.strftime("%Y-%m-%d"),
            "market": market,
            "model": "LightGBM_Alpha158",
            "candidates": results,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n[Pipeline] 候选股保存: {output_file}")
    return results, pred_date


def run_uzi_analysis(ticker: str, mode="quick"):
    """调用 UZI Skill 分析单只股票

    mode:
      - 'quick': 快速扫描 (run.py --no-browser)
      - 'deep':  完整深度分析
    """
    uzi_root = UZI_SKILL_DIR
    run_script = uzi_root / "run.py"

    if not run_script.exists():
        print(f"[UZI] 错误: 找不到 {run_script}")
        return None

    cmd = [str(VENV_PYTHON), str(run_script), ticker, "--no-browser"]
    print(f"\n[UZI] 分析股票: {ticker} (模式: {mode})")
    print(f"[UZI] 命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(uzi_root),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            print(f"[UZI] {ticker} 分析完成")
        else:
            print(f"[UZI] {ticker} 分析异常 (exit={result.returncode})")
            if result.stderr:
                print(f"[UZI] stderr: {result.stderr[:500]}")
        return result
    except subprocess.TimeoutExpired:
        print(f"[UZI] {ticker} 分析超时 (>600s)")
        return None


def generate_summary(candidates, pred_date, uzi_results):
    """生成综合报告摘要"""
    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "prediction_date": str(pred_date),
        "total_candidates": len(candidates),
        "analysis_results": [],
    }

    for c in candidates:
        entry = {
            "rank": c["rank"],
            "ticker": c["ticker"],
            "qlib_score": c["score"],
            "uzi_status": "analyzed" if c["ticker"] in uzi_results else "pending",
        }
        summary["analysis_results"].append(entry)

    output_file = OUTPUT_DIR / f"pipeline_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print("  Pipeline 完成摘要")
    print(f"{'=' * 60}")
    print(f"  预测日期: {pred_date}")
    print(f"  候选数量: {len(candidates)}")
    print(f"  已分析:   {sum(1 for r in summary['analysis_results'] if r['uzi_status'] == 'analyzed')}")
    print(f"  报告路径: {output_file}")
    print(f"{'=' * 60}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="qlib选股 → UZI深度分析 Pipeline")
    parser.add_argument("--market", default="csi300", help="市场指数 (csi300/csi500)")
    parser.add_argument("--top", type=int, default=5, help="选出前N只股票")
    parser.add_argument("--skip-qlib", action="store_true", help="跳过qlib选股，直接用--tickers")
    parser.add_argument("--tickers", nargs="+", help="直接指定股票代码 (跳过qlib)")
    parser.add_argument("--skip-uzi", action="store_true", help="只选股不分析")
    parser.add_argument("--uzi-mode", default="quick", choices=["quick", "deep"], help="UZI分析模式")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  qlib + UZI 量化选股深度分析 Pipeline")
    print("=" * 60)

    if args.skip_qlib and args.tickers:
        candidates = [
            {"rank": i + 1, "ticker": t, "ticker_short": t, "qlib_code": t, "score": 0.0}
            for i, t in enumerate(args.tickers)
        ]
        pred_date = datetime.now()
        print(f"\n[Pipeline] 跳过qlib，直接分析: {args.tickers}")
    else:
        print("\n[阶段 1/2] qlib 量化选股")
        print("-" * 40)
        candidates, pred_date = run_qlib_selection(
            market=args.market, top_n=args.top
        )

    if not args.skip_uzi:
        print(f"\n[阶段 2/2] UZI 深度分析 (共 {len(candidates)} 只)")
        print("-" * 40)
        uzi_results = {}
        for c in candidates:
            ticker = c["ticker_short"]
            result = run_uzi_analysis(ticker, mode=args.uzi_mode)
            if result:
                uzi_results[c["ticker"]] = result
    else:
        uzi_results = {}
        print("\n[Pipeline] 已跳过 UZI 分析")

    summary = generate_summary(candidates, pred_date, uzi_results)
    return summary


if __name__ == "__main__":
    main()
