"""Backfill daily broad-market index bars used only as a point-in-time gate."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import baostock as bs
import pandas as pd

from config import PROJECT_ROOT


INDEX_CODES = {
    "SH000001": "sh.000001",  # SSE Composite
    "SZ399001": "sz.399001",  # SZSE Component
    "SZ399006": "sz.399006",  # ChiNext
    "SH000300": "sh.000300",  # CSI 300
}
INDEX_DIR = PROJECT_ROOT / "data_lake" / "raw" / "baostock" / "index_daily"


def fetch_index(instrument: str, code: str, start: str, end: str) -> pd.DataFrame:
    fields = "date,open,high,low,close,volume,amount"
    query = bs.query_history_k_data_plus(
        code,
        fields,
        start_date=pd.to_datetime(start).strftime("%Y-%m-%d"),
        end_date=pd.to_datetime(end).strftime("%Y-%m-%d"),
        frequency="d",
        adjustflag="3",
    )
    if query.error_code != "0":
        raise RuntimeError(f"{code}: {query.error_code} {query.error_msg}")
    rows: list[list[str]] = []
    while query.next():
        rows.append(query.get_row_data())
    frame = pd.DataFrame(rows, columns=query.fields)
    if frame.empty:
        return frame
    frame.insert(0, "instrument", instrument)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    for column in ("open", "high", "low", "close", "volume", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["date", "close"]).drop_duplicates("date").sort_values("date")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill BaoStock broad-market daily indices")
    parser.add_argument("--start", default="20260501")
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    args = parser.parse_args()
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    try:
        for instrument, code in INDEX_CODES.items():
            frame = fetch_index(instrument, code, args.start, args.end)
            if frame.empty:
                print(f"{instrument}: no rows", flush=True)
                continue
            path = INDEX_DIR / f"{instrument}.parquet"
            frame.to_parquet(path, index=False, compression="zstd")
            print(f"{instrument}: {len(frame)} rows -> {path}", flush=True)
    finally:
        bs.logout()


if __name__ == "__main__":
    main()
