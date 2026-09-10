#!/usr/bin/env python3
"""V4.17-A point-in-time announcement backfill.

This script builds a source-faithful historical announcement lake from the
Eastmoney announcement archive exposed by AKShare ``stock_notice_report``.

Scientific rule:
- the archive exposes an announcement *date*, not a historical intraday
  publication timestamp;
- therefore historical rows are DATE precision and MUST NOT be used for
  same-day intraday decisions;
- ``retrieved_at`` is the ingestion time of this backfill and is never treated
  as historical ``first_seen_at``.

No alpha construction happens in this file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import akshare as ak
import pandas as pd

SCHEMA_VERSION = "v4.17-a.1"
SOURCE_PROVIDER = "eastmoney"
SOURCE_ENDPOINT = "akshare.stock_notice_report"
SOURCE_SYMBOL = "全部"
CAUSAL_USE_POLICY = "NEXT_TRADING_DAY_ONLY"
EXPECTED_COLUMNS = {"代码", "名称", "公告标题", "公告类型", "公告日期", "网址"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="YYYY-MM-DD, inclusive")
    p.add_argument("--end", required=True, help="YYYY-MM-DD, inclusive")
    p.add_argument(
        "--output-root",
        default="data_lake/raw/eastmoney/notices",
        help="Parquet root; output is partitioned by year",
    )
    p.add_argument(
        "--manifest-root",
        default="data_lake/manifests",
        help="Request ledgers are written here",
    )
    p.add_argument("--sleep", type=float, default=0.25)
    p.add_argument("--max-retries", type=int, default=5)
    p.add_argument("--resume", action="store_true")
    p.add_argument(
        "--allow-errors",
        action="store_true",
        help="Persist unresolved request errors instead of exiting non-zero",
    )
    return p.parse_args()


def daterange(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def normalize_instrument(raw_code: object) -> str | None:
    s = str(raw_code).strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = s.zfill(6)
    if len(s) != 6 or not s.isdigit():
        return None

    # A-share equity families only.  The Eastmoney announcement endpoint can
    # also emit convertible bonds and other securities; those remain outside
    # this equity event lake rather than being silently mis-mapped.
    if s.startswith(("600", "601", "603", "605", "688", "689")):
        return f"SH{s}"
    if s.startswith(("000", "001", "002", "003", "200", "300", "301")):
        return f"SZ{s}"
    if s.startswith(("4", "8", "920")):
        return f"BJ{s}"
    return None


def stable_json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_frame(raw: pd.DataFrame, retrieved_at: str) -> tuple[pd.DataFrame, int]:
    if raw is None or raw.empty:
        return pd.DataFrame(), 0

    missing = EXPECTED_COLUMNS - set(raw.columns)
    if missing:
        raise ValueError(f"stock_notice_report schema drift; missing columns: {sorted(missing)}; got={list(raw.columns)}")

    rows: list[dict] = []
    non_equity = 0
    for rec in raw.to_dict("records"):
        raw_code = str(rec.get("代码", "")).strip()
        if raw_code.endswith(".0"):
            raw_code = raw_code[:-2]
        raw_code = raw_code.zfill(6)
        instrument = normalize_instrument(raw_code)
        if instrument is None:
            non_equity += 1
            continue

        published = pd.to_datetime(rec.get("公告日期"), errors="coerce")
        if pd.isna(published):
            raise ValueError(f"unparseable 公告日期 for row: {rec}")
        published_date = published.date().isoformat()
        title = str(rec.get("公告标题", "")).strip()
        source_url = str(rec.get("网址", "")).strip()
        stock_name = str(rec.get("名称", "")).strip()
        announcement_type = str(rec.get("公告类型", "")).strip()

        raw_canonical = {
            "代码": raw_code,
            "名称": stock_name,
            "公告标题": title,
            "公告类型": announcement_type,
            "公告日期": published_date,
            "网址": source_url,
        }
        raw_payload_hash = sha256_text(stable_json(raw_canonical))
        identity = "|".join(
            [SOURCE_PROVIDER, published_date, raw_code, title, source_url]
        )

        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "event_id": sha256_text(identity),
                "source_provider": SOURCE_PROVIDER,
                "source_endpoint": SOURCE_ENDPOINT,
                "event_type": "corporate_announcement",
                "published_date": published_date,
                "published_at": pd.NaT,
                "timestamp_precision": "date",
                "stock_code_raw": raw_code,
                "instrument": instrument,
                "stock_name": stock_name,
                "title": title,
                "announcement_type": announcement_type,
                "source_url": source_url,
                "retrieved_at": retrieved_at,
                "first_seen_at": pd.NaT,
                "causal_use_policy": CAUSAL_USE_POLICY,
                "raw_payload_hash": raw_payload_hash,
            }
        )

    out = pd.DataFrame(rows)
    if not out.empty:
        out["published_date"] = pd.to_datetime(out["published_date"]).dt.date.astype(str)
        out["published_at"] = pd.to_datetime(out["published_at"], utc=True)
        out["first_seen_at"] = pd.to_datetime(out["first_seen_at"], utc=True)
        out["retrieved_at"] = pd.to_datetime(out["retrieved_at"], utc=True)
        out = out.drop_duplicates("event_id", keep="last").sort_values(
            ["published_date", "instrument", "event_id"]
        )
    return out, non_equity


def fetch_one_day(day: date, max_retries: int, base_sleep: float) -> tuple[pd.DataFrame, int, str | None]:
    ymd = day.strftime("%Y%m%d")
    last_error: str | None = None
    for attempt in range(1, max_retries + 1):
        try:
            frame = ak.stock_notice_report(symbol=SOURCE_SYMBOL, date=ymd)
            return frame, attempt, None
        except Exception as exc:  # network/provider failures are ledgered
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < max_retries:
                delay = base_sleep * (2 ** (attempt - 1)) + random.uniform(0.0, 0.15)
                time.sleep(delay)
    return pd.DataFrame(), max_retries, last_error


def read_existing_ledger(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"request_date": str})
    return df


def atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)


def atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(tmp, index=False)
    tmp.replace(path)


def main() -> None:
    args = parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end must be >= --start")
    if start.year != end.year:
        raise SystemExit("collector intentionally accepts one calendar year per invocation")

    year = start.year
    output_root = Path(args.output_root)
    manifest_root = Path(args.manifest_root)
    parquet_path = output_root / f"year={year}" / f"notices_{year}.parquet"
    ledger_path = manifest_root / f"v4_17_eastmoney_notice_requests_{year}.csv"

    existing_ledger = read_existing_ledger(ledger_path) if args.resume else pd.DataFrame()
    done_dates: set[str] = set()
    if not existing_ledger.empty:
        done_dates = set(
            existing_ledger.loc[
                existing_ledger["status"].isin(["success", "empty"]), "request_date"
            ].astype(str)
        )

    existing_events = pd.read_parquet(parquet_path) if args.resume and parquet_path.exists() else pd.DataFrame()
    event_frames: list[pd.DataFrame] = [existing_events] if not existing_events.empty else []
    ledger_rows: list[dict] = existing_ledger.to_dict("records") if not existing_ledger.empty else []

    unresolved = 0
    for day in daterange(start, end):
        ds = day.isoformat()
        if ds in done_dates:
            continue

        request_started = datetime.now(timezone.utc)
        raw, attempts, error = fetch_one_day(day, args.max_retries, args.sleep)
        retrieved_at = datetime.now(timezone.utc).isoformat()

        if error is not None:
            unresolved += 1
            status = "error"
            normalized = pd.DataFrame()
            non_equity = 0
        else:
            normalized, non_equity = normalize_frame(raw, retrieved_at)
            status = "empty" if raw is None or raw.empty else "success"
            if not normalized.empty:
                event_frames.append(normalized)

        ledger_rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "request_date": ds,
                "source_provider": SOURCE_PROVIDER,
                "source_endpoint": SOURCE_ENDPOINT,
                "symbol": SOURCE_SYMBOL,
                "status": status,
                "attempts": attempts,
                "raw_rows": 0 if raw is None else int(len(raw)),
                "equity_rows": int(len(normalized)),
                "non_equity_rows": int(non_equity),
                "error": error or "",
                "request_started_at": request_started.isoformat(),
                "retrieved_at": retrieved_at,
            }
        )

        # Persist progress after every request.  A long backfill can resume
        # without silently treating an interrupted date as complete.
        ledger_df = pd.DataFrame(ledger_rows)
        ledger_df = ledger_df.sort_values(["request_date", "retrieved_at"]).drop_duplicates(
            "request_date", keep="last"
        )
        atomic_write_csv(ledger_df, ledger_path)

        if event_frames:
            combined = pd.concat(event_frames, ignore_index=True)
            combined = combined.drop_duplicates("event_id", keep="last").sort_values(
                ["published_date", "instrument", "event_id"]
            )
            atomic_write_parquet(combined, parquet_path)
            event_frames = [combined]

        time.sleep(max(0.0, args.sleep))

    final_ledger = read_existing_ledger(ledger_path)
    errors = final_ledger[final_ledger["status"] == "error"] if not final_ledger.empty else pd.DataFrame()
    events = pd.read_parquet(parquet_path) if parquet_path.exists() else pd.DataFrame()
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "year": year,
                "requested_start": start.isoformat(),
                "requested_end": end.isoformat(),
                "request_days": int(len(final_ledger)),
                "unresolved_errors": int(len(errors)),
                "events": int(len(events)),
                "unique_instruments": int(events["instrument"].nunique()) if not events.empty else 0,
                "causal_use_policy": CAUSAL_USE_POLICY,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if (unresolved or len(errors)) and not args.allow_errors:
        raise SystemExit(f"unresolved provider errors remain: {max(unresolved, len(errors))}")


if __name__ == "__main__":
    main()
