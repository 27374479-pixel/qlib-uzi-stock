"""Run V4 paired execution over TraderHarness 2021-2026 history."""
from __future__ import annotations

import argparse
from pathlib import Path

import v4_intraday_survivor_validation as base
import v4_paired_execution as paired
import v4_survivor_wrapper as survivor

ROOT = Path(__file__).resolve().parent
paired.PAIRED_CODES = ROOT / "output" / "v4_paired_ext_codes.txt"
paired.PAIRED_MINUTE_FILES = tuple(
    ROOT / "data_lake" / "raw" / "traderharness" / f"paired_ext_5min_{year}.parquet"
    for year in range(2021, 2027)
)


def prepare_codes() -> None:
    cfg = base.Config(start="2015-01-01", end="2026-09-03")
    frame = survivor.prepare(cfg)
    paired.write_paired_codes(frame, "2021-01-04")


def run() -> None:
    cfg = paired.Config(
        start="2015-01-01",
        end="2026-09-03",
        sample_start="2021-01-04",
        entry_times=("14:30", "14:45", "14:55"),
        exit_times=("09:30", "10:00", "15:00"),
        min_side_sizes=(5, 10),
        bootstrap_samples=5000,
        seed=20260906,
        output="output/v4_paired_execution_2021_2026.json",
    )
    paired.run(cfg)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare-codes", action="store_true")
    args = ap.parse_args()
    if args.prepare_codes:
        prepare_codes()
    else:
        run()
