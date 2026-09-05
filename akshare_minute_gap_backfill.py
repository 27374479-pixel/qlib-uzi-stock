"""Conservative AKShare minute-gap backfill for v4 validation.

This collector is intentionally polite: single-threaded, resumable, sleeps
between symbols, skips histories already covered by any local source, and
stops after repeated provider failures. It uses Eastmoney through AKShare and
stores unadjusted executable 5-minute prices in the existing Eastmoney cache.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

import akshare as ak
import pandas as pd

from config import PROJECT_ROOT

OUT = PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "equity_5min"
SOURCE_DIRS = (
    OUT,
    PROJECT_ROOT / "data_lake" / "raw" / "baostock" / "equity_5min",
    PROJECT_ROOT / "data_lake" / "raw" / "sina" / "equity_5min",
)


def normalize(raw: pd.DataFrame, instrument: str) -> pd.DataFrame:
    mapping = {
        "时间": "datetime", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount", "振幅": "amplitude_pct",
        "涨跌幅": "change_pct", "涨跌额": "change",
        "换手率": "turnover_rate_pct",
    }
    frame = raw.rename(columns=mapping).copy()
    if frame.empty or "datetime" not in frame:
        return pd.DataFrame()
    frame.insert(0, "instrument", instrument)
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
    for col in ("open", "close", "high", "low", "volume", "amount",
                "amplitude_pct", "change_pct", "change", "turnover_rate_pct"):
        if col in frame:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["source"] = "eastmoney_5min_via_akshare"
    frame["knowledge_time"] = frame["datetime"]
    frame["downloaded_at"] = datetime.now().isoformat(timespec="seconds")
    return (frame.dropna(subset=["datetime", "open", "close"])
            .drop_duplicates(["instrument", "datetime"], keep="last")
            .sort_values("datetime").reset_index(drop=True))


def read_local(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_parquet(path)
        if "datetime" not in frame:
            return pd.DataFrame()
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
        return frame.dropna(subset=["datetime"])
    except Exception:
        return pd.DataFrame()


def covered(instrument: str, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    for directory in SOURCE_DIRS:
        frame = read_local(directory / f"{instrument}.parquet")
        if frame.empty:
            continue
        lo = frame["datetime"].min().normalize()
        hi = frame["datetime"].max().normalize()
        if lo <= start and hi >= end - pd.Timedelta(days=4):
            return True
    return False


def save(frame: pd.DataFrame, instrument: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{instrument}.parquet"
    cached = read_local(path)
    if not cached.empty:
        frame = pd.concat([cached, frame], ignore_index=True, sort=False)
        frame = (frame.drop_duplicates(["instrument", "datetime"], keep="last")
                 .sort_values("datetime").reset_index(drop=True))
    tmp = path.with_suffix(".parquet.tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--codes-file", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--sleep", type=float, default=2.0)
    p.add_argument("--max-codes", type=int, default=0)
    p.add_argument("--max-consecutive-failures", type=int, default=8)
    args = p.parse_args()
    start = pd.to_datetime(args.start).normalize()
    end = pd.to_datetime(args.end).normalize()
    codes = [x.strip() for x in Path(args.codes_file).read_text(encoding="utf-8").splitlines() if x.strip()]
    missing = [x for x in codes if not covered(x, start, end)]
    if args.max_codes:
        missing = missing[:args.max_codes]
    print(f"AKShare polite gap fill: requested={len(codes)} missing={len(missing)} sleep={args.sleep}s", flush=True)
    ok = fail = consecutive = 0
    for i, instrument in enumerate(missing, 1):
        try:
            raw = ak.stock_zh_a_hist_min_em(
                symbol=instrument[2:],
                start_date=f"{start:%Y-%m-%d} 09:30:00",
                end_date=f"{end:%Y-%m-%d} 15:00:00",
                period="5",
                adjust="",
            )
            frame = normalize(raw, instrument)
            if frame.empty:
                raise ValueError("empty response")
            actual_start = frame["datetime"].min().normalize()
            actual_end = frame["datetime"].max().normalize()
            if actual_start > start or actual_end < end - pd.Timedelta(days=4):
                raise ValueError(f"insufficient coverage {actual_start.date()}..{actual_end.date()}")
            save(frame, instrument)
            ok += 1
            consecutive = 0
            print(f"[{i}/{len(missing)}] {instrument} ok rows={len(frame)} total_ok={ok} fail={fail}", flush=True)
        except Exception as exc:
            fail += 1
            consecutive += 1
            print(f"[{i}/{len(missing)}] {instrument} failed: {exc} consecutive={consecutive}", flush=True)
            if consecutive >= args.max_consecutive_failures:
                print("provider appears unhealthy; stopping politely", flush=True)
                break
        time.sleep(max(0.0, args.sleep))
    print(f"AKShare gap fill finished ok={ok} failed={fail}", flush=True)


if __name__ == "__main__":
    main()
