"""Collect a point-in-time market/event snapshot for ``uzi-daily-desk``.

Tencent supplies broad quotes when Eastmoney's all-stock endpoint is blocked;
Eastmoney/AKShare supplies the specialist limit-up pools.  The output is raw
evidence and WATCH candidates, never an order list.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import akshare as ak
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
INSTRUMENTS = ROOT / "qlib_data" / "cn_data" / "instruments"


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def current_constituents(universe: str) -> tuple[list[str], str]:
    rows: list[list[str]] = []
    path = INSTRUMENTS / f"{universe}.txt"
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            rows.append(parts)
    frame = pd.DataFrame(rows, columns=["instrument", "start", "end"])
    frame["end"] = pd.to_datetime(frame["end"])
    latest = frame["end"].max()
    codes = sorted(frame.loc[frame["end"].eq(latest), "instrument"].drop_duplicates())
    return codes, str(latest.date())


def tencent_quotes(instruments: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for offset in range(0, len(instruments), 30):
        symbols = [
            ("sh" if item.startswith("SH") else "sz") + item[2:]
            for item in instruments[offset : offset + 30]
        ]
        url = "http://qt.gtimg.cn/q=" + ",".join(symbols)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            text = urllib.request.urlopen(request, timeout=15).read().decode("gbk", "replace")
        except Exception as exc:
            print(f"Tencent batch {offset // 30 + 1} failed: {type(exc).__name__}: {exc}", flush=True)
            continue
        for line in text.split(";"):
            if "=" not in line:
                continue
            fields = line.split("=", 1)[1].strip().strip('"').split("~")
            if len(fields) <= 38:
                continue
            rows.append(
                {
                    "name": fields[1],
                    "code": fields[2],
                    "price": _number(fields[3]),
                    "preclose": _number(fields[4]),
                    "open": _number(fields[5]),
                    "pct": _number(fields[32]),
                    "high": _number(fields[33]),
                    "low": _number(fields[34]),
                    "amount": _number(fields[37]),
                    "turnover": _number(fields[38]),
                }
            )
        time.sleep(0.03)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.loc[
        frame["price"].gt(0) & ~frame["name"].str.upper().str.contains("ST", na=False)
    ].drop_duplicates("code", keep="last")


def event_pools(date: str) -> dict[str, pd.DataFrame]:
    functions = {
        "limit_up": ak.stock_zt_pool_em,
        "broken": ak.stock_zt_pool_zbgc_em,
        "limit_down": ak.stock_zt_pool_dtgc_em,
        "previous": ak.stock_zt_pool_previous_em,
    }
    result: dict[str, pd.DataFrame] = {}
    for name, function in functions.items():
        try:
            result[name] = function(date=date)
        except Exception as exc:
            print(f"Eastmoney {name} failed: {type(exc).__name__}: {exc}", flush=True)
            result[name] = pd.DataFrame()
    return result


def _records(frame: pd.DataFrame, columns: list[str], n: int = 30) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    present = [column for column in columns if column in frame.columns]
    return json.loads(frame[present].head(n).to_json(orient="records", force_ascii=False))


def build_snapshot(universe: str, date: str) -> dict[str, Any]:
    knowledge_time = datetime.now().astimezone().isoformat(timespec="seconds")
    instruments, constituent_date = current_constituents(universe)
    quotes = tencent_quotes(instruments)
    pools = event_pools(date)

    pct = pd.to_numeric(quotes.get("pct", pd.Series(dtype=float)), errors="coerce").dropna()
    market = {
        "universe": universe,
        "constituent_snapshot_end": constituent_date,
        "quote_count": int(len(pct)),
        "up": int((pct > 0).sum()),
        "down": int((pct < 0).sum()),
        "flat": int((pct == 0).sum()),
        "up_ratio": float((pct > 0).mean()) if len(pct) else None,
        "down_ratio": float((pct < 0).mean()) if len(pct) else None,
        "breadth": float((pct > 0).mean() - (pct < 0).mean()) if len(pct) else None,
        "median_pct": float(pct.median()) if len(pct) else None,
        "gain_ge_5": int((pct >= 5).sum()),
        "loss_le_minus_5": int((pct <= -5).sum()),
    }

    limit_up, broken, limit_down, previous = (
        pools["limit_up"], pools["broken"], pools["limit_down"], pools["previous"]
    )
    touched = len(limit_up) + len(broken)
    event_summary = {
        "limit_up": int(len(limit_up)),
        "broken": int(len(broken)),
        "limit_down": int(len(limit_down)),
        "previous_pool": int(len(previous)),
        "board_quality": float(len(limit_up) / touched) if touched else None,
    }

    themes = pd.concat(
        [
            limit_up.assign(state="sealed"),
            broken.assign(state="broken"),
        ],
        ignore_index=True,
    )
    if not themes.empty and "所属行业" in themes:
        theme_table = themes.groupby("所属行业").agg(
            touched=("代码", "size"),
            sealed=("state", lambda x: int((x == "sealed").sum())),
            broken=("state", lambda x: int((x == "broken").sum())),
            mean_pct=("涨跌幅", "mean"),
        ).reset_index()
        theme_table["quality"] = theme_table["sealed"] / theme_table["touched"]
        theme_table = theme_table.sort_values(["touched", "quality"], ascending=False)
    else:
        theme_table = pd.DataFrame()

    previous_feedback = previous.copy()
    feedback: dict[str, Any] = {"count": int(len(previous_feedback))}
    if not previous_feedback.empty:
        returns = pd.to_numeric(previous_feedback["涨跌幅"], errors="coerce")
        feedback.update(
            {
                "mean_pct": float(returns.mean()),
                "median_pct": float(returns.median()),
                "positive_ratio": float((returns > 0).mean()),
                "strong_ge_3": int((returns >= 3).sum()),
                "weak_le_minus_3": int((returns <= -3).sum()),
            }
        )

    sealed_codes = set(limit_up.get("代码", pd.Series(dtype=str)).astype(str))
    broken_codes = set(broken.get("代码", pd.Series(dtype=str)).astype(str))
    watch = previous.loc[
        ~previous["代码"].astype(str).isin(sealed_codes)
        & pd.to_numeric(previous["涨跌幅"], errors="coerce").between(-3.0, 7.0)
        & pd.to_numeric(previous["换手率"], errors="coerce").between(1.0, 25.0)
    ].copy() if not previous.empty else pd.DataFrame()
    if not watch.empty:
        watch["current_broken"] = watch["代码"].astype(str).isin(broken_codes)
        watch["watch_score"] = (
            pd.to_numeric(watch["昨日连板数"], errors="coerce").fillna(0) * 1.5
            + pd.to_numeric(watch["涨跌幅"], errors="coerce").clip(-3, 7) * 0.25
            - watch["current_broken"].astype(float) * 2
        )
        watch = watch.sort_values("watch_score", ascending=False)

    return {
        "asof": knowledge_time,
        "trade_date": date,
        "sources": {
            "breadth": "Tencent qt.gtimg.cn point-in-time quotes",
            "events": "Eastmoney limit pools via AKShare",
        },
        "market": market,
        "events": event_summary,
        "previous_feedback": feedback,
        "industry_proxy": _records(
            theme_table, ["所属行业", "touched", "sealed", "broken", "quality", "mean_pct"], 20
        ),
        "sealed_leaders": _records(
            limit_up,
            ["代码", "名称", "涨跌幅", "换手率", "首次封板时间", "最后封板时间", "炸板次数", "连板数", "涨停统计", "所属行业"],
            30,
        ),
        "broken_boards": _records(
            broken,
            ["代码", "名称", "涨跌幅", "换手率", "首次封板时间", "炸板次数", "涨停统计", "所属行业"],
            30,
        ),
        "watch_from_previous": _records(
            watch,
            ["代码", "名称", "涨跌幅", "最新价", "换手率", "涨速", "振幅", "昨日连板数", "涨停统计", "所属行业", "current_broken", "watch_score"],
            30,
        ),
        "limitations": [
            "Eastmoney 所属行业 is an industry proxy, not a verified event reason.",
            "The Qlib constituent snapshot date is reported and may lag today.",
            "WATCH rows require a separate completed-bar divergence/stabilization trigger before PROBE.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="csi800")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    snapshot = build_snapshot(args.universe, args.date)
    output = Path(args.output) if args.output else ROOT / "output" / "live_uzi_desk" / f"{args.date}_{datetime.now():%H%M%S}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    print(f"snapshot: {output}")


if __name__ == "__main__":
    main()
