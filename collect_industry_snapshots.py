"""Collect point-in-time CSRC industry snapshots from BaoStock."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import baostock as bs
import pandas as pd

from config import PROJECT_ROOT
from factor_transfer_backtest import calendar
from multi_expert_oos_backtest import Config as BacktestConfig, signal_dates


INDUSTRY_DIR = PROJECT_ROOT / "data_lake" / "raw" / "baostock" / "industry_snapshots"
MANIFEST_DIR = PROJECT_ROOT / "data_lake" / "manifests"


def baostock_to_qlib(code: str) -> str | None:
    match = re.fullmatch(r"(sh|sz)\.(\d{6})", str(code).lower())
    return f"{match.group(1).upper()}{match.group(2)}" if match else None


def industry_code(value: str) -> str | None:
    match = re.match(r"^([A-Za-z]\d{2})", str(value).strip())
    return match.group(1).upper() if match else None


def fetch_snapshot(date: pd.Timestamp) -> pd.DataFrame:
    result = bs.query_stock_industry(date=str(pd.Timestamp(date).date()))
    if result.error_code != "0":
        raise RuntimeError(f"BaoStock industry {date.date()}: {result.error_code} {result.error_msg}")
    rows = []
    while result.next():
        rows.append(result.get_row_data())
    frame = pd.DataFrame(rows, columns=result.fields)
    if frame.empty:
        raise ValueError(f"Empty industry snapshot for {date.date()}")
    frame = frame.rename(
        columns={
            "updateDate": "provider_update_date",
            "code_name": "instrument_name",
            "industryClassification": "classification_standard",
        }
    )
    frame["instrument"] = frame["code"].map(baostock_to_qlib)
    frame["industry_code"] = frame["industry"].map(industry_code)
    frame["snapshot_date"] = pd.Timestamp(date)
    frame["provider_update_date"] = pd.to_datetime(frame["provider_update_date"], errors="coerce")
    frame["source"] = "baostock"
    result_frame = frame[
        [
            "snapshot_date",
            "instrument",
            "instrument_name",
            "industry_code",
            "industry",
            "classification_standard",
            "provider_update_date",
            "source",
        ]
    ].dropna(subset=["instrument", "industry_code"])
    return result_frame.drop_duplicates(["snapshot_date", "instrument"], keep="last").sort_values("instrument")


def collect_snapshots(dates: list[pd.Timestamp], resume: bool = True, retries: int = 3) -> dict:
    INDUSTRY_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_msg}")
    records = []
    failures = []
    skipped = 0
    started = datetime.now(timezone.utc)
    try:
        for number, date in enumerate(dates, 1):
            destination = INDUSTRY_DIR / f"{date:%Y%m%d}.parquet"
            if resume and destination.exists():
                skipped += 1
                continue
            error = None
            for attempt in range(1, retries + 1):
                try:
                    frame = fetch_snapshot(date)
                    temporary = destination.with_suffix(".tmp.parquet")
                    frame.to_parquet(temporary, index=False, compression="zstd")
                    temporary.replace(destination)
                    records.append(
                        {
                            "snapshot_date": str(date.date()),
                            "rows": len(frame),
                            "industry_codes": int(frame["industry_code"].nunique()),
                            "provider_update_max": str(frame["provider_update_date"].max().date()),
                        }
                    )
                    error = None
                    break
                except Exception as exc:
                    error = str(exc)
                    if attempt < retries:
                        time.sleep(attempt)
            if error:
                failures.append({"snapshot_date": str(date.date()), "error": error})
            if number == 1 or number % 10 == 0:
                print(
                    f"  industry {number}/{len(dates)} new={len(records)} skipped={skipped} failed={len(failures)}",
                    flush=True,
                )
    finally:
        bs.logout()
    manifest = {
        "provider": "BaoStock",
        "dataset": "point-in-time CSRC industry snapshots",
        "requested_dates": len(dates),
        "downloaded": len(records),
        "skipped_existing": skipped,
        "failed": failures,
        "snapshots": records,
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = MANIFEST_DIR / f"baostock_industry_{stamp}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest: {path}", flush=True)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect point-in-time industry snapshots")
    parser.add_argument("--start", default="2015-01-05")
    parser.add_argument("--end", default="2026-05-29")
    parser.add_argument("--holding-days", type=int, default=21)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> dict:
    args = parse_args()
    config = BacktestConfig(start=args.start, end=args.end, holding_days=args.holding_days)
    dates = signal_dates(calendar(), config)
    if args.limit is not None:
        dates = dates[: args.limit]
    print(f"Collecting {len(dates)} point-in-time industry snapshots", flush=True)
    return collect_snapshots(dates, resume=not args.no_resume)


if __name__ == "__main__":
    main()
