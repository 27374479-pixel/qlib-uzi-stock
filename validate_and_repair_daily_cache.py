"""Validate persisted BaoStock daily parquet files and repair only corrupt symbols.

This is intentionally separate from alpha logic.  The goal is to make the durable
Git/LFS data lake self-healing without re-downloading healthy instruments.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from point_in_time_data import BAOSTOCK_DAILY_DIR, CollectionConfig, collect, validate_frame


REQUIRED_COLUMNS = {
    "instrument",
    "date",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "amount",
    "turnover_rate_pct",
    "trade_status",
    "is_st",
    "float_market_cap_est",
}


def validate_path(path: Path) -> tuple[bool, str]:
    try:
        # Read the full file, not only metadata.  This catches page/header
        # corruption that may only surface when PyArrow materializes columns.
        frame = pd.read_parquet(path)
        missing = sorted(REQUIRED_COLUMNS.difference(frame.columns))
        if missing:
            return False, f"missing columns: {missing}"
        quality = validate_frame(frame)
        if not quality.get("valid", False):
            return False, f"quality check failed: {quality}"
        instrument = str(frame["instrument"].iloc[0]).upper() if not frame.empty else ""
        if instrument != path.stem.upper():
            return False, f"instrument/path mismatch: frame={instrument} path={path.stem.upper()}"
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def scan(paths: list[Path]) -> list[tuple[Path, str]]:
    bad: list[tuple[Path, str]] = []
    for number, path in enumerate(paths, 1):
        valid, reason = validate_path(path)
        if not valid:
            bad.append((path, reason))
            print(f"BAD {path.name}: {reason}", flush=True)
        if number == 1 or number % 100 == 0:
            print(f"validated {number}/{len(paths)} bad={len(bad)}", flush=True)
    return bad


def run(start: str, end: str, retries: int, retry_delay: float) -> int:
    paths = sorted(BAOSTOCK_DAILY_DIR.glob("*.parquet"))
    if not paths:
        raise SystemExit(f"no daily parquet files under {BAOSTOCK_DAILY_DIR}")

    print(f"integrity scan: {len(paths)} daily parquet files", flush=True)
    bad = scan(paths)
    if not bad:
        print("daily parquet integrity: PASS (no repair needed)", flush=True)
        return 0

    symbols = [path.stem.upper() for path, _ in bad]
    print(f"repairing {len(symbols)} corrupt symbols only: {symbols}", flush=True)
    for path, _ in bad:
        path.unlink(missing_ok=True)

    cfg = CollectionConfig(
        start=start,
        end=end,
        market="csi800",
        retry_count=retries,
        retry_delay_seconds=retry_delay,
    )
    result = collect(cfg, symbols, resume=False)
    failed = result.get("failed", [])
    if failed:
        raise SystemExit(f"repair provider failures: {failed}")

    repaired_paths = [BAOSTOCK_DAILY_DIR / f"{symbol}.parquet" for symbol in symbols]
    bad_after = scan(repaired_paths)
    if bad_after:
        details = "; ".join(f"{path.name}: {reason}" for path, reason in bad_after)
        raise SystemExit(f"parquet integrity still failing after repair: {details}")

    print(f"daily parquet integrity: PASS after repairing {len(symbols)} symbols", flush=True)
    return len(symbols)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate/repair persisted BaoStock daily parquet cache")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--retries", type=int, default=8)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.start, args.end, args.retries, args.retry_delay)
