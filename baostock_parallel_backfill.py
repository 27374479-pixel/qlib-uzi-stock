"""Run independent, resumable BaoStock collectors on disjoint code shards.

This launcher is intentionally conservative: each worker owns distinct
instrument files and its own BaoStock login session.  It exists to test and,
when allowed by the provider, accelerate the otherwise serial collector; it
does not merge or overwrite another worker's symbol.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

import pandas as pd

from baostock_minute_backfill import collect, load_codes, normalize_code, instrument_from_code


@dataclass(frozen=True)
class Job:
    instruments: list[str]
    start: pd.Timestamp
    end: pd.Timestamp
    retries: int
    retry_delay: float


def _run_job(job: Job) -> dict:
    return collect(
        job.instruments,
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
    parser = argparse.ArgumentParser(description="Conservative parallel BaoStock 5-minute backfill")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--universe", choices=["events", "existing", "csi800", "csi800_start"], default="csi800_start")
    parser.add_argument("--codes", default="")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=1.0)
    args = parser.parse_args()
    start = _parse_date(args.start)
    end = _parse_date(args.end)
    instruments = _codes(args, start)
    workers = max(1, min(args.workers, len(instruments))) if instruments else 0
    if not instruments:
        raise ValueError("no SH/SZ instruments selected")
    shards = [instruments[index::workers] for index in range(workers)]
    print(f"Parallel BaoStock probe: instruments={len(instruments)} workers={workers}", flush=True)
    jobs = [Job(shard, start, end, max(1, args.retries), max(0.0, args.retry_delay)) for shard in shards if shard]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_job, job) for job in jobs]
        for number, future in enumerate(as_completed(futures), 1):
            result = future.result()
            print(
                f"worker {number}/{len(futures)} downloaded={result['downloaded']} "
                f"skipped={result['skipped_existing']} failed={len(result['failed'])}",
                flush=True,
            )


if __name__ == "__main__":
    main()
