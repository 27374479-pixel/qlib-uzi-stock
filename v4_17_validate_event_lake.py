#!/usr/bin/env python3
"""Validate V4.17-A Eastmoney announcement event lake.

This validator is intentionally strict about causal semantics. Historical
Eastmoney notice rows currently carry date precision only, so they may not be
used for same-day intraday research.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta, timezone, datetime
from pathlib import Path

import pandas as pd

SCHEMA_VERSION = "v4.17-a.1"
REQUIRED_EVENT_COLUMNS = {
    "schema_version",
    "event_id",
    "source_provider",
    "source_endpoint",
    "event_type",
    "published_date",
    "published_at",
    "timestamp_precision",
    "stock_code_raw",
    "instrument",
    "stock_name",
    "title",
    "announcement_type",
    "source_url",
    "retrieved_at",
    "first_seen_at",
    "causal_use_policy",
    "raw_payload_hash",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--event-root", default="data_lake/raw/eastmoney/notices")
    p.add_argument("--manifest-root", default="data_lake/manifests")
    p.add_argument("--output", default="output/v4_17_event_lake_validation.json")
    return p.parse_args()


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def fail_if(condition: bool, message: str, failures: list[str]) -> None:
    if condition:
        failures.append(message)


def main() -> None:
    args = parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    event_root = Path(args.event_root)
    manifest_root = Path(args.manifest_root)

    event_files = sorted(event_root.glob("year=*/notices_*.parquet"))
    if not event_files:
        raise SystemExit(f"no event parquet files under {event_root}")

    frames = []
    for path in event_files:
        df = pd.read_parquet(path)
        missing = REQUIRED_EVENT_COLUMNS - set(df.columns)
        if missing:
            raise SystemExit(f"{path}: missing columns {sorted(missing)}")
        frames.append(df)
    events = pd.concat(frames, ignore_index=True)

    ledger_files = sorted(manifest_root.glob("v4_17_eastmoney_notice_requests_*.csv"))
    if not ledger_files:
        raise SystemExit("no V4.17 request ledgers found")
    ledgers = pd.concat([pd.read_csv(p, dtype={"request_date": str}) for p in ledger_files], ignore_index=True)
    ledgers = ledgers.sort_values(["request_date", "retrieved_at"]).drop_duplicates("request_date", keep="last")

    failures: list[str] = []
    expected_dates = {d.isoformat() for d in daterange(start, end)}
    observed_dates = set(ledgers["request_date"].astype(str))
    missing_request_dates = sorted(expected_dates - observed_dates)
    extra_request_dates = sorted(observed_dates - expected_dates)
    unresolved = ledgers[ledgers["status"] == "error"].copy()

    fail_if(bool(missing_request_dates), f"missing request dates: {missing_request_dates[:20]}", failures)
    fail_if(bool(extra_request_dates), f"unexpected request dates: {extra_request_dates[:20]}", failures)
    fail_if(not unresolved.empty, f"unresolved provider errors: {len(unresolved)}", failures)
    fail_if(not set(ledgers["status"]).issubset({"success", "empty"}), "unexpected request status", failures)

    fail_if(events["event_id"].isna().any(), "null event_id", failures)
    fail_if(events["event_id"].duplicated().any(), f"duplicate event_id: {int(events['event_id'].duplicated().sum())}", failures)
    fail_if(events["published_date"].isna().any(), "null published_date", failures)
    fail_if(events["instrument"].isna().any(), "null instrument", failures)
    fail_if(events["title"].fillna("").str.strip().eq("").any(), "blank title", failures)
    fail_if(events["raw_payload_hash"].isna().any(), "null raw_payload_hash", failures)
    fail_if(not events["instrument"].astype(str).str.match(r"^(SH|SZ|BJ)\d{6}$").all(), "invalid instrument format", failures)
    fail_if(not set(events["timestamp_precision"].dropna()) <= {"date", "datetime"}, "invalid timestamp_precision", failures)

    date_precision = events[events["timestamp_precision"] == "date"]
    fail_if(
        not date_precision["published_at"].isna().all(),
        "date-precision rows must not fabricate published_at",
        failures,
    )
    fail_if(
        not date_precision["first_seen_at"].isna().all(),
        "historical date-precision rows must not fabricate first_seen_at",
        failures,
    )
    fail_if(
        not date_precision["causal_use_policy"].eq("NEXT_TRADING_DAY_ONLY").all(),
        "date-precision rows must be NEXT_TRADING_DAY_ONLY",
        failures,
    )

    event_dates = pd.to_datetime(events["published_date"], errors="coerce").dt.date
    fail_if(event_dates.isna().any(), "unparseable event published_date", failures)
    if not event_dates.isna().any():
        fail_if((event_dates < start).any() or (event_dates > end).any(), "event outside requested interval", failures)

    fail_if(not events["schema_version"].eq(SCHEMA_VERSION).all(), "schema version mismatch", failures)
    fail_if(not events["source_provider"].eq("eastmoney").all(), "mixed source_provider in Eastmoney lake", failures)
    fail_if(not events["source_endpoint"].eq("akshare.stock_notice_report").all(), "unexpected source_endpoint", failures)

    status_counts = {str(k): int(v) for k, v in ledgers["status"].value_counts(dropna=False).items()}
    type_counts = {str(k): int(v) for k, v in events["announcement_type"].fillna("<NA>").value_counts().items()}
    yearly_counts = {
        str(k): int(v)
        for k, v in pd.to_datetime(events["published_date"]).dt.year.value_counts().sort_index().items()
    }

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "source": {
            "provider": "eastmoney",
            "endpoint": "akshare.stock_notice_report",
            "historical_timestamp_precision": "date",
            "causal_use_policy": "NEXT_TRADING_DAY_ONLY",
            "warning": "retrieved_at is ingestion time, not historical first_seen_at",
        },
        "coverage": {
            "expected_calendar_days": len(expected_dates),
            "request_days": int(len(ledgers)),
            "request_status_counts": status_counts,
            "missing_request_dates": missing_request_dates,
            "unresolved_error_dates": unresolved["request_date"].astype(str).tolist(),
            "event_rows": int(len(events)),
            "unique_events": int(events["event_id"].nunique()),
            "unique_instruments": int(events["instrument"].nunique()),
            "min_published_date": str(events["published_date"].min()) if not events.empty else None,
            "max_published_date": str(events["published_date"].max()) if not events.empty else None,
            "yearly_event_counts": yearly_counts,
            "announcement_type_counts": type_counts,
        },
        "quality": {
            "duplicate_event_ids": int(events["event_id"].duplicated().sum()),
            "blank_titles": int(events["title"].fillna("").str.strip().eq("").sum()),
            "source_url_coverage": float(events["source_url"].fillna("").str.strip().ne("").mean()) if len(events) else 0.0,
            "all_date_precision_causally_delayed": bool(
                date_precision["causal_use_policy"].eq("NEXT_TRADING_DAY_ONLY").all()
            ),
        },
        "validation": {
            "pass": not failures,
            "failures": failures,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if failures:
        raise SystemExit("V4.17 event-lake validation failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
