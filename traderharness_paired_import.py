"""Import the selected+control universe for V4.1 from TraderHarness HF data.

The six 2025/2026 objects are downloaded sequentially and filtered locally.
No per-symbol market-data API is used. Only the paired-universe slices are
persisted; raw public objects are discarded after each year is filtered.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import duckdb
import pandas as pd
from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parent
REPO_ID = "ANTICH/traderharness-ashare-5y"
PROBE = ROOT / "output" / "traderharness_hf_probe.json"
CODES_FILE = ROOT / "output" / "v4_paired_codes.txt"
OUT_DIR = ROOT / "data_lake" / "raw" / "traderharness"
MANIFEST = ROOT / "output" / "traderharness_paired_5min_manifest.json"
DOWNLOAD_ROOT = ROOT / ".cache" / "traderharness_hf_paired"


def _q(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _download(remote_path: str, sleep_seconds: float, retries: int) -> Path:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            local = Path(hf_hub_download(
                repo_id=REPO_ID,
                repo_type="dataset",
                filename=remote_path,
                local_dir=str(DOWNLOAD_ROOT),
            ))
            if not local.is_file() or local.stat().st_size <= 0:
                raise RuntimeError(f"empty download: {local}")
            print(f"downloaded {remote_path} bytes={local.stat().st_size}", flush=True)
            time.sleep(max(0.0, sleep_seconds))
            return local
        except Exception as exc:
            last = exc
            cooldown = min(600.0, 60.0 * (2 ** (attempt - 1)))
            print(f"download failed {remote_path} attempt={attempt}/{retries}: {exc}; cooldown={cooldown:.0f}s", flush=True)
            time.sleep(cooldown)
    raise RuntimeError(f"failed to download {remote_path}: {last}")


def _load_targets() -> tuple[pd.DataFrame, dict[int, list[str]]]:
    if not PROBE.exists():
        raise FileNotFoundError(f"missing probe: {PROBE}")
    if not CODES_FILE.exists():
        raise FileNotFoundError(f"missing paired code set: {CODES_FILE}")
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    paths = probe.get("target_2025_2026", {}).get("paths", [])
    by_year = {2025: [], 2026: []}
    for remote in paths:
        for year in by_year:
            if f"year={year}/" in remote:
                by_year[year].append(remote)
    if any(not by_year[y] for y in by_year):
        raise RuntimeError(f"probe missing target year partitions: {by_year}")

    instruments = [x.strip() for x in CODES_FILE.read_text(encoding="utf-8").splitlines() if x.strip()]
    mapping = pd.DataFrame({"instrument": instruments, "stock_code": [x[2:] for x in instruments]})
    if mapping.empty:
        raise RuntimeError("paired code set is empty")
    if mapping["stock_code"].duplicated().any():
        raise RuntimeError("duplicate stock codes in paired universe")
    return mapping, by_year


def _filter_year(year: int, paths: list[Path], mapping: pd.DataFrame, end_date: str) -> dict[str, object]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"paired_5min_{year}.parquet"
    tmp = out.with_suffix(".tmp.parquet")
    tmp.unlink(missing_ok=True)

    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.register("paired_codes", mapping)
    path_sql = ",".join(f"'{_q(p)}'" for p in paths)
    cutoff = f" AND m.datetime < TIMESTAMP '{end_date} 23:59:59'" if year == 2026 else ""
    con.execute(f"""
        COPY (
            SELECT
                c.instrument,
                CAST(m.stock_code AS VARCHAR) AS stock_code,
                CAST(m.date AS DATE) AS date,
                CAST(m.datetime AS TIMESTAMP) AS datetime,
                CAST(m.open AS DOUBLE) AS open,
                CAST(m.high AS DOUBLE) AS high,
                CAST(m.low AS DOUBLE) AS low,
                CAST(m.close AS DOUBLE) AS close,
                CAST(m.volume AS DOUBLE) AS volume,
                CAST(m.amount AS DOUBLE) AS amount,
                'traderharness_hf' AS source
            FROM read_parquet([{path_sql}]) AS m
            INNER JOIN paired_codes AS c
              ON CAST(m.stock_code AS VARCHAR) = c.stock_code
            WHERE m.datetime >= TIMESTAMP '{year}-01-01 00:00:00'
              {cutoff}
            ORDER BY c.instrument, m.datetime
        ) TO '{_q(tmp)}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 50000)
    """)
    tmp.replace(out)
    stats = con.execute(f"""
        SELECT COUNT(*), COUNT(DISTINCT instrument), MIN(datetime), MAX(datetime),
               COUNT(*) - COUNT(DISTINCT instrument || '|' || CAST(datetime AS VARCHAR))
        FROM read_parquet('{_q(out)}')
    """).fetchone()
    con.close()
    rec = {
        "year": year,
        "path": str(out.relative_to(ROOT)),
        "bytes": int(out.stat().st_size),
        "rows": int(stats[0]),
        "instruments": int(stats[1]),
        "min_datetime": str(stats[2]),
        "max_datetime": str(stats[3]),
        "duplicate_rows": int(stats[4]),
    }
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    if rec["rows"] <= 0 or rec["instruments"] <= 0:
        raise RuntimeError(f"empty paired output for {year}")
    if rec["duplicate_rows"] != 0:
        raise RuntimeError(f"duplicate minute keys in paired {year}: {rec['duplicate_rows']}")
    return rec


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sleep", type=float, default=20.0)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--end", default="2026-09-03")
    args = p.parse_args()

    mapping, by_year = _load_targets()
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    results = []
    for year in (2025, 2026):
        local_paths = [_download(remote, args.sleep, args.retries) for remote in by_year[year]]
        results.append(_filter_year(year, local_paths, mapping, args.end))
        year_dir = DOWNLOAD_ROOT / "5min_clean" / f"year={year}"
        if year_dir.exists():
            shutil.rmtree(year_dir)

    payload = {
        "source_repo": REPO_ID,
        "source_paths": by_year,
        "paired_instruments_requested": int(len(mapping)),
        "end": args.end,
        "outputs": results,
        "total_filtered_bytes": int(sum(x["bytes"] for x in results)),
        "total_rows": int(sum(x["rows"] for x in results)),
    }
    MANIFEST.parent.mkdir(exist_ok=True)
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
