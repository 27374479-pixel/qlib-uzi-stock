"""Resumable GitHub-friendly CSI800 BaoStock 5-minute backfill.

This wrapper freezes CSI800 at a historical date from BaoStock HS300+ZZ500
constituents, downloads only missing symbols through baostock_minute_backfill,
and persists a small JSON state so later GitHub Actions runs do not need to
pull every previously committed LFS parquet just to know what is complete.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import baostock as bs
import pandas as pd

from baostock_minute_backfill import (
    BAOSTOCK_MINUTE_DIR,
    MANIFEST_DIR,
    _already_covers,
    _parse_date,
    collect,
)
from config import PROJECT_ROOT
from eastmoney_recent_backfill import instrument_from_code, normalize_code

UNIVERSE_DIR = PROJECT_ROOT / "data_lake" / "universe"
STATE_DIR = PROJECT_ROOT / "data_lake" / "state"


def _query_constituents(query: Callable[..., Any], asof: pd.Timestamp) -> list[dict[str, str]]:
    rs = query(date=asof.strftime("%Y-%m-%d"))
    if str(rs.error_code) != "0":
        raise RuntimeError(f"constituent query failed: {rs.error_code} {rs.error_msg}")
    rows: list[dict[str, str]] = []
    while rs.next():
        rows.append(dict(zip(rs.fields, rs.get_row_data())))
    return rows


def freeze_csi800(asof: pd.Timestamp) -> tuple[list[str], dict[str, Any]]:
    login = bs.login()
    if str(login.error_code) != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    try:
        hs300 = _query_constituents(bs.query_hs300_stocks, asof)
        zz500 = _query_constituents(bs.query_zz500_stocks, asof)
    finally:
        bs.logout()

    by_code: dict[str, dict[str, str]] = {}
    for family, rows in (("hs300", hs300), ("zz500", zz500)):
        for row in rows:
            code = normalize_code(row.get("code"))
            if not code:
                continue
            instrument = instrument_from_code(code)
            if instrument is None or not instrument.startswith(("SH", "SZ")):
                continue
            by_code[code] = {
                "code": code,
                "instrument": instrument,
                "name": str(row.get("code_name", "")),
                "family": family,
                "update_date": str(row.get("updateDate", row.get("update_date", ""))),
            }

    codes = sorted(by_code)
    if not 760 <= len(codes) <= 820:
        raise ValueError(
            f"Unexpected frozen CSI800 size {len(codes)} at {asof.date()}; "
            "expected roughly 800 HS300+ZZ500 constituents"
        )

    UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"csi800_{asof.strftime('%Y%m%d')}"
    (UNIVERSE_DIR / f"{stem}.txt").write_text("\n".join(codes) + "\n", encoding="utf-8")
    payload = {
        "asof": asof.strftime("%Y-%m-%d"),
        "source": "BaoStock query_hs300_stocks + query_zz500_stocks",
        "count": len(codes),
        "constituents": [by_code[code] for code in codes],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    (UNIVERSE_DIR / f"{stem}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return codes, payload


def _state_path(asof: pd.Timestamp, start: pd.Timestamp, end: pd.Timestamp) -> Path:
    return STATE_DIR / (
        f"github_baostock_csi800_{asof.strftime('%Y%m%d')}_"
        f"{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.json"
    )


def _load_state(path: Path, config: dict[str, str]) -> dict[str, Any]:
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
        if state.get("config") == config:
            return state
    return {
        "config": config,
        "completed": [],
        "attempts": {},
        "runs": [],
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }


def run_batch(
    asof: pd.Timestamp,
    start: pd.Timestamp,
    end: pd.Timestamp,
    batch_size: int,
    retries: int,
    retry_delay: float,
    page_size: int,
) -> dict[str, Any]:
    codes, universe = freeze_csi800(asof)
    instruments = [item for item in (instrument_from_code(code) for code in codes) if item]

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    state_path = _state_path(asof, start, end)
    config = {
        "asof": asof.strftime("%Y%m%d"),
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
    }
    state = _load_state(state_path, config)
    completed = set(map(str, state.get("completed", [])))

    # Reconcile only real parquet files available in this checkout. Git-LFS
    # pointer files fail parquet reads and remain governed by the JSON state.
    for instrument in instruments:
        if instrument in completed:
            continue
        try:
            if _already_covers(BAOSTOCK_MINUTE_DIR / f"{instrument}.parquet", start, end):
                completed.add(instrument)
        except Exception:
            pass

    missing = [item for item in instruments if item not in completed]
    selected = missing[: max(1, batch_size)]
    manifest: dict[str, Any] | None = None
    if selected:
        manifest = collect(
            selected,
            start,
            end,
            retries=max(1, retries),
            retry_delay=max(0.0, retry_delay),
            page_size=max(2000, page_size),
        )

    attempts = state.setdefault("attempts", {})
    newly_completed: list[str] = []
    for instrument in selected:
        attempts[instrument] = int(attempts.get(instrument, 0)) + 1
        try:
            if _already_covers(BAOSTOCK_MINUTE_DIR / f"{instrument}.parquet", start, end):
                completed.add(instrument)
                newly_completed.append(instrument)
        except Exception:
            pass

    remaining = [item for item in instruments if item not in completed]
    run_record = {
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "selected": selected,
        "newly_completed": newly_completed,
        "completed_count": len(completed),
        "expected_count": len(instruments),
        "coverage_ratio": len(completed) / len(instruments) if instruments else 0.0,
        "remaining_count": len(remaining),
        "manifest_failed": (manifest or {}).get("failed", []),
    }
    state["completed"] = sorted(completed)
    state["runs"].append(run_record)
    state["updated_utc"] = run_record["finished_utc"]
    state["universe_count"] = universe["count"]
    state["remaining_preview"] = remaining[:50]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_path = PROJECT_ROOT / "output" / "github_csi800_minute_status.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "state_file": str(state_path.relative_to(PROJECT_ROOT)),
        "universe_file": f"data_lake/universe/csi800_{asof.strftime('%Y%m%d')}.txt",
        **run_record,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resumable GitHub CSI800 BaoStock 5-minute batch")
    parser.add_argument("--asof", default="20250102")
    parser.add_argument("--start", default="20241001")
    parser.add_argument("--end", default="20260903")
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=1.0)
    parser.add_argument("--page-size", type=int, default=10000)
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    asof = _parse_date(args.asof)
    start = _parse_date(args.start)
    end = _parse_date(args.end)
    if not start <= asof <= end:
        raise ValueError("expected start <= asof <= end")
    return run_batch(
        asof,
        start,
        end,
        batch_size=max(1, args.batch_size),
        retries=max(1, args.retries),
        retry_delay=max(0.0, args.retry_delay),
        page_size=max(2000, args.page_size),
    )


if __name__ == "__main__":
    main()
