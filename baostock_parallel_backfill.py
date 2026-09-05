"""Parallel, resumable BaoStock 5-minute backfill.

Each process handles exactly one instrument at a time.  This prevents a slow
symbol from holding an entire shard hostage and makes progress visible and
restartable at symbol granularity.  The underlying collector writes each
instrument atomically and skips files that already cover the requested range.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

import pandas as pd

from baostock_minute_backfill import collect, load_codes, normalize_code, instrument_from_code


@dataclass(frozen=True)
class Job:
    instrument: str
    start: pd.Timestamp
    end: pd.Timestamp
    retries: int
    retry_delay: float


def _run_job(job: Job) -> dict:
    return collect(
        [job.instrument],
        job.start,
        job.end,
        retries=job.retries,
        retry_delay=job.retry_delay,
    )


def _parse_date(value: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"invalid date: {value}")
    return parsed.normalize()


def _codes(args: argparse.Namespace, start: pd.Timestamp) -> list[str]:
    if args.codes:
        result = []
        for raw in args.codes.split(","):
            code = normalize_code(raw.strip())
            instrument = instrument_from_code(code) if code else None
            if instrument and instrument[:2] in {"SH", "SZ"}:
                result.append(instrument)
        return sorted(set(result))
    return load_codes(args.universe, None, asof=start)


def main() -> None:
    parser = argparse.ArgumentParser(description="Symbol-resumable parallel BaoStock 5-minute backfill")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--universe", choices=["events", "existing", "csi800", "csi800_start"], default="csi800_start")
    parser.add_argument("--codes", default="")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-delay", type=float, default=1.0)
    args = parser.parse_args()

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    instruments = _codes(args, start)
    if not instruments:
        raise ValueError("no SH/SZ instruments selected")
    workers = max(1, min(args.workers, len(instruments)))
    jobs = [Job(x, start, end, max(1, args.retries), max(0.0, args.retry_delay)) for x in instruments]
    print(f"BaoStock symbol-resumable backfill: instruments={len(jobs)} workers={workers}", flush=True)

    downloaded = skipped = failed = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        future_to_symbol = {pool.submit(_run_job, job): job.instrument for job in jobs}
        for number, future in enumerate(as_completed(future_to_symbol), 1):
            symbol = future_to_symbol[future]
            try:
                result = future.result()
                downloaded += int(result.get("downloaded", 0))
                skipped += int(result.get("skipped_existing", 0))
                failed += len(result.get("failed", []))
                status = "failed" if result.get("failed") else ("skipped" if result.get("skipped_existing") else "downloaded")
            except Exception as exc:
                failed += 1
                status = f"exception:{exc}"
            print(
                f"[{number}/{len(jobs)}] {symbol} {status} totals downloaded={downloaded} skipped={skipped} failed={failed}",
                flush=True,
            )

    print(f"completed downloaded={downloaded} skipped={skipped} failed={failed}", flush=True)


if __name__ == "__main__":
    main()
