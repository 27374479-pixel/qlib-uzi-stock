#!/usr/bin/env python3
"""Deterministically merge isolated V4.17 backfill shards into canonical yearly files.

Each shard is collected in its own temporary/artifact root.  This merger never
silently resolves overlapping shard windows: duplicate request dates across
shards are a configuration error and fail the merge.  Event IDs must also be
unique across shards so accidental overlap cannot be hidden by de-duplication.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input-root", required=True, help="root containing downloaded shard artifacts")
    p.add_argument("--start", required=True, help="YYYY-MM-DD inclusive")
    p.add_argument("--end", required=True, help="YYYY-MM-DD inclusive")
    p.add_argument("--event-root", default="data_lake/raw/eastmoney/notices")
    p.add_argument("--manifest-root", default="data_lake/manifests")
    p.add_argument("--report", default="output/v4_17_shard_merge.json")
    return p.parse_args()


def year_from_event_path(path: Path) -> int:
    parent = path.parent.name
    if not parent.startswith("year="):
        raise ValueError(f"cannot infer year from event path: {path}")
    return int(parent.split("=", 1)[1])


def year_from_ledger_path(path: Path) -> int:
    return int(path.stem.rsplit("_", 1)[1])


def main() -> None:
    args = parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end must be >= --start")

    input_root = Path(args.input_root)
    event_root = Path(args.event_root)
    manifest_root = Path(args.manifest_root)
    report_path = Path(args.report)
    requested_years = set(range(start.year, end.year + 1))

    event_files = [
        p
        for p in sorted(input_root.glob("**/data_lake/raw/eastmoney/notices/year=*/notices_*.parquet"))
        if year_from_event_path(p) in requested_years
    ]
    ledger_files = [
        p
        for p in sorted(input_root.glob("**/data_lake/manifests/v4_17_eastmoney_notice_requests_*.csv"))
        if year_from_ledger_path(p) in requested_years
    ]
    if not ledger_files:
        raise SystemExit(f"no shard request ledgers found under {input_root}")

    failures: list[str] = []
    yearly: list[dict] = []

    event_root.mkdir(parents=True, exist_ok=True)
    manifest_root.mkdir(parents=True, exist_ok=True)

    for year in sorted(requested_years):
        year_event_files = [p for p in event_files if year_from_event_path(p) == year]
        year_ledger_files = [p for p in ledger_files if year_from_ledger_path(p) == year]

        ledger_frames = [pd.read_csv(p, dtype={"request_date": str}) for p in year_ledger_files]
        if not ledger_frames:
            failures.append(f"{year}: no request ledgers found")
            yearly.append({"year": year, "event_shards": len(year_event_files), "ledger_shards": 0})
            continue

        ledgers = pd.concat(ledger_frames, ignore_index=True)
        duplicate_request_dates = sorted(
            ledgers.loc[ledgers["request_date"].duplicated(keep=False), "request_date"]
            .astype(str)
            .unique()
            .tolist()
        )
        if duplicate_request_dates:
            failures.append(
                f"{year}: overlapping shard request dates: {duplicate_request_dates[:20]}"
            )

        request_dates = pd.to_datetime(ledgers["request_date"], errors="coerce").dt.date
        invalid_request_dates = int(request_dates.isna().sum())
        outside_request_window = int(
            ((request_dates.notna()) & ((request_dates < start) | (request_dates > end))).sum()
        )
        if invalid_request_dates:
            failures.append(f"{year}: invalid request dates: {invalid_request_dates}")
        if outside_request_window:
            failures.append(f"{year}: request rows outside requested window: {outside_request_window}")

        ledgers = ledgers.sort_values(["request_date", "retrieved_at"]).reset_index(drop=True)
        manifest_path = manifest_root / f"v4_17_eastmoney_notice_requests_{year}.csv"
        ledgers.to_csv(manifest_path, index=False)

        events = pd.DataFrame()
        duplicate_event_ids = 0
        if year_event_files:
            event_frames = [pd.read_parquet(p) for p in year_event_files]
            events = pd.concat(event_frames, ignore_index=True)
            if "event_id" not in events.columns:
                failures.append(f"{year}: event shards missing event_id")
            else:
                duplicate_event_ids = int(events["event_id"].duplicated(keep=False).sum())
                if duplicate_event_ids:
                    failures.append(
                        f"{year}: duplicate event IDs across shards: {duplicate_event_ids}"
                    )

            if "published_date" not in events.columns:
                failures.append(f"{year}: event shards missing published_date")
            else:
                published = pd.to_datetime(events["published_date"], errors="coerce").dt.date
                invalid_published = int(published.isna().sum())
                outside_events = int(
                    ((published.notna()) & ((published < start) | (published > end))).sum()
                )
                if invalid_published:
                    failures.append(f"{year}: invalid published dates: {invalid_published}")
                if outside_events:
                    failures.append(f"{year}: event rows outside requested window: {outside_events}")

            sort_cols = [c for c in ["published_date", "instrument", "event_id"] if c in events.columns]
            if sort_cols:
                events = events.sort_values(sort_cols).reset_index(drop=True)
            parquet_path = event_root / f"year={year}" / f"notices_{year}.parquet"
            parquet_path.parent.mkdir(parents=True, exist_ok=True)
            events.to_parquet(parquet_path, index=False)

        yearly.append(
            {
                "year": year,
                "event_shards": len(year_event_files),
                "ledger_shards": len(year_ledger_files),
                "request_rows": int(len(ledgers)),
                "event_rows": int(len(events)),
                "duplicate_request_dates": len(duplicate_request_dates),
                "duplicate_event_rows": duplicate_event_ids,
            }
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "input_root": str(input_root),
        "event_shard_files": len(event_files),
        "ledger_shard_files": len(ledger_files),
        "yearly": yearly,
        "pass": not failures,
        "failures": failures,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if failures:
        raise SystemExit("V4.17 shard merge failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
