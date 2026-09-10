#!/usr/bin/env python3
"""Build V4.17-A point-in-time Eastmoney announcement archive.

The source endpoint exposes a publication DATE, not a trustworthy historical
intraday timestamp. Therefore every historical row is deliberately date
precision and can only be consumed from the next trading session.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

SCHEMA_VERSION = "v4.17-a.2"
SOURCE_PROVIDER = "eastmoney"
SOURCE_ENDPOINT = "akshare.stock_notice_report"
CAUSAL_USE_POLICY = "NEXT_TRADING_DAY_ONLY"
REQUIRED_SOURCE_COLUMNS = {"代码", "名称", "公告标题", "公告类型", "公告日期", "网址"}
EVENT_COLUMNS = [
    "schema_version", "event_id", "source_provider", "source_endpoint",
    "event_type", "archive_request_date", "published_date", "published_at",
    "timestamp_precision", "stock_code_raw", "instrument", "stock_name",
    "title", "announcement_type", "source_url", "retrieved_at",
    "first_seen_at", "causal_use_policy", "raw_payload_hash",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--event-root", default="data_lake/raw/eastmoney/notices")
    p.add_argument("--manifest-root", default="data_lake/manifests")
    p.add_argument("--symbol", default="全部")
    p.add_argument("--max-retries", type=int, default=6)
    p.add_argument("--sleep-seconds", type=float, default=0.30)
    p.add_argument("--strict", action="store_true")
    return p.parse_args()


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def infer_a_share(code_raw: object) -> str | None:
    digits = re.sub(r"\D", "", str(code_raw or ""))
    if len(digits) < 6:
        return None
    code = digits[-6:]
    if code.startswith("200"):
        return None
    if code.startswith(("600", "601", "603", "605", "688")):
        return "SH" + code
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return "SZ" + code
    if code.startswith(("43", "83", "87", "88", "92")):
        return "BJ" + code
    return None


def canonical_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def raw_hash(payload: dict[str, str]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def event_id(payload: dict[str, str]) -> str:
    url = payload.get("source_url", "")
    match = re.search(r"\b(AN\d{8,})\b", url, flags=re.IGNORECASE)
    identity = f"{SOURCE_PROVIDER}|{match.group(1).upper()}" if match else (
        f"{SOURCE_PROVIDER}|{payload['published_date']}|{payload['stock_code_raw']}|"
        f"{payload['announcement_type']}|{payload['title']}|{url}"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def fetch_day(day: date, symbol: str, retries: int, base_sleep: float) -> pd.DataFrame:
    import akshare as ak

    ymd = day.strftime("%Y%m%d")
    last: Exception | None = None
    for attempt in range(retries):
        try:
            df = ak.stock_notice_report(symbol=symbol, date=ymd)
            if df is None:
                return pd.DataFrame(columns=sorted(REQUIRED_SOURCE_COLUMNS))
            missing = REQUIRED_SOURCE_COLUMNS - set(df.columns)
            if missing and not df.empty:
                raise RuntimeError(f"source schema drift on {ymd}: missing {sorted(missing)}; got {list(df.columns)}")
            return df
        except Exception as exc:
            last = exc
            if attempt + 1 == retries:
                break
            time.sleep(base_sleep * (2 ** min(attempt, 4)) + random.uniform(0, base_sleep))
    raise RuntimeError(f"{ymd}: provider failed after {retries} attempts: {last}")


def normalize(df: pd.DataFrame, request_day: date, retrieved_at: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, r in df.iterrows():
        published = pd.to_datetime(r.get("公告日期"), errors="coerce")
        if pd.isna(published):
            continue
        published_date = published.date().isoformat()
        # Critical archive contract: a date query may only populate that same date.
        if published_date != request_day.isoformat():
            raise RuntimeError(
                f"archive date mismatch: requested={request_day.isoformat()} returned={published_date}"
            )
        stock_code_raw = canonical_text(r.get("代码"))
        instrument = infer_a_share(stock_code_raw)
        if instrument is None:
            continue
        payload = {
            "published_date": published_date,
            "stock_code_raw": stock_code_raw,
            "stock_name": canonical_text(r.get("名称")),
            "title": canonical_text(r.get("公告标题")),
            "announcement_type": canonical_text(r.get("公告类型")),
            "source_url": canonical_text(r.get("网址")),
        }
        if not payload["title"]:
            continue
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id(payload),
            "source_provider": SOURCE_PROVIDER,
            "source_endpoint": SOURCE_ENDPOINT,
            "event_type": "announcement",
            "archive_request_date": request_day.isoformat(),
            "published_date": published_date,
            "published_at": None,
            "timestamp_precision": "date",
            "stock_code_raw": stock_code_raw,
            "instrument": instrument,
            "stock_name": payload["stock_name"],
            "title": payload["title"],
            "announcement_type": payload["announcement_type"],
            "source_url": payload["source_url"],
            "retrieved_at": retrieved_at,
            "first_seen_at": None,
            "causal_use_policy": CAUSAL_USE_POLICY,
            "raw_payload_hash": raw_hash(payload),
        })
    out = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    if not out.empty:
        out = out.drop_duplicates("event_id", keep="last").sort_values(
            ["published_date", "instrument", "event_id"]
        ).reset_index(drop=True)
    return out


def write_year_partition(root: Path, year: int, fresh: pd.DataFrame) -> None:
    path = root / f"year={year}" / f"notices_{year}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_parquet(path)
        combined = pd.concat([old, fresh], ignore_index=True, sort=False)
    else:
        combined = fresh.copy()
    combined = combined[EVENT_COLUMNS].drop_duplicates("event_id", keep="last")
    combined = combined.sort_values(["published_date", "instrument", "event_id"]).reset_index(drop=True)
    tmp = path.with_suffix(".parquet.tmp")
    combined.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def write_year_ledger(root: Path, year: int, fresh: pd.DataFrame) -> None:
    path = root / f"v4_17_eastmoney_notice_requests_{year}.csv"
    root.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_csv(path, dtype={"request_date": str})
        combined = pd.concat([old, fresh], ignore_index=True, sort=False)
    else:
        combined = fresh.copy()
    combined = combined.sort_values(["request_date", "retrieved_at"]).drop_duplicates("request_date", keep="last")
    tmp = path.with_suffix(".csv.tmp")
    combined.to_csv(tmp, index=False)
    tmp.replace(path)


def main() -> int:
    args = parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end must be >= --start")

    event_root = Path(args.event_root)
    manifest_root = Path(args.manifest_root)
    event_frames: list[pd.DataFrame] = []
    ledger_rows: list[dict[str, object]] = []
    failures = 0

    days = list(daterange(start, end))
    for i, day in enumerate(days, 1):
        retrieved_at = datetime.now(timezone.utc).isoformat()
        try:
            raw = fetch_day(day, args.symbol, args.max_retries, args.sleep_seconds)
            norm = normalize(raw, day, retrieved_at)
            event_frames.append(norm)
            status = "success" if len(norm) else "empty"
            ledger_rows.append({
                "request_date": day.isoformat(), "status": status,
                "source_rows": int(len(raw)), "kept_a_share_rows": int(len(norm)),
                "retrieved_at": retrieved_at, "error": "",
            })
            print(f"[{i}/{len(days)}] {day} {status} source={len(raw)} kept={len(norm)}")
        except Exception as exc:
            failures += 1
            ledger_rows.append({
                "request_date": day.isoformat(), "status": "error",
                "source_rows": 0, "kept_a_share_rows": 0,
                "retrieved_at": retrieved_at, "error": str(exc),
            })
            print(f"[{i}/{len(days)}] {day} ERROR {exc}")
        time.sleep(max(args.sleep_seconds, 0.0))

    events = pd.concat(event_frames, ignore_index=True) if event_frames else pd.DataFrame(columns=EVENT_COLUMNS)
    if not events.empty:
        events = events.drop_duplicates("event_id", keep="last")
        for year, part in events.groupby(pd.to_datetime(events["published_date"]).dt.year):
            write_year_partition(event_root, int(year), part.copy())

    ledger = pd.DataFrame(ledger_rows)
    for year, part in ledger.groupby(pd.to_datetime(ledger["request_date"]).dt.year):
        write_year_ledger(manifest_root, int(year), part.copy())

    summary = {
        "schema_version": SCHEMA_VERSION,
        "requested_start": start.isoformat(), "requested_end": end.isoformat(),
        "calendar_days": len(days), "event_rows_this_run": int(len(events)),
        "unique_events_this_run": int(events["event_id"].nunique()) if len(events) else 0,
        "failed_days_this_run": failures,
        "causal_use_policy": CAUSAL_USE_POLICY,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.strict and failures:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
