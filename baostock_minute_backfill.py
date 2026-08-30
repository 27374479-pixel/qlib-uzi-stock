"""Serial BaoStock intraday backfill for the five-style short-term replay.

BaoStock's historical 5-minute endpoint is materially deeper than the local
Sina/AKShare cache.  The provider is session-oriented, so this collector is
deliberately serial and resumable.  Raw files are kept under the BaoStock
namespace; the replay loader applies source priority when sources overlap:

    Eastmoney direct > BaoStock 5-minute > Sina/AKShare 5-minute.

The collector uses ``adjustflag=3`` (unadjusted), which matches executable
prices and the direct Eastmoney collector.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import baostock as bs
import baostock.common.contants as bs_constants
import numpy as np
import pandas as pd

from config import PROJECT_ROOT
from eastmoney_recent_backfill import (
    instrument_from_code,
    load_universe,
    local_event_codes,
    normalize_code,
)


BAOSTOCK_MINUTE_DIR = PROJECT_ROOT / "data_lake" / "raw" / "baostock" / "equity_5min"
MANIFEST_DIR = PROJECT_ROOT / "data_lake" / "manifests"
FIELDS = "date,time,open,high,low,close,volume,amount"
OUTPUT_COLUMNS = [
    "instrument",
    "datetime",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
    "amplitude_pct",
    "change_pct",
    "change",
    "turnover_rate_pct",
    "source",
    "knowledge_time",
    "downloaded_at",
]


def _parse_date(value: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"invalid date: {value}")
    return parsed.normalize()


def _baostock_code(instrument: str) -> str:
    code = normalize_code(instrument) or ""
    if code.startswith("6"):
        return f"sh.{code}"
    if code.startswith(("0", "2", "3")):
        return f"sz.{code}"
    raise ValueError(f"BaoStock does not support instrument {instrument!r}")


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def _read_cached(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()
    if frame.empty:
        return frame
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
    return frame.dropna(subset=["datetime"])


def _normalise_rows(
    rows: list[list[str]],
    instrument: str,
    downloaded_at: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    frame = pd.DataFrame(rows, columns=FIELDS.split(","))
    # BaoStock's time is YYYYMMDDHHMMSSmmm.  The millisecond suffix is not
    # needed for 5-minute bars, but retaining the exact minute is important.
    frame["datetime"] = pd.to_datetime(
        frame["time"].astype(str).str[:14], format="%Y%m%d%H%M%S", errors="coerce"
    )
    frame = frame.loc[frame["datetime"].between(start, end + pd.Timedelta(days=1))].copy()
    if frame.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    for column in ("open", "close", "high", "low", "volume", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame.insert(0, "instrument", instrument)
    frame["amplitude_pct"] = np.nan
    frame["change_pct"] = np.nan
    frame["change"] = np.nan
    frame["turnover_rate_pct"] = np.nan
    frame["source"] = "baostock_5min"
    frame["knowledge_time"] = frame["datetime"]
    frame["downloaded_at"] = downloaded_at
    return (
        frame[OUTPUT_COLUMNS]
        .dropna(subset=["datetime", "open", "close", "high", "low"])
        .drop_duplicates(["instrument", "datetime"], keep="last")
        .sort_values("datetime")
        .reset_index(drop=True)
    )


def _query_symbol(
    instrument: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    downloaded_at: str,
) -> pd.DataFrame:
    result = bs.query_history_k_data_plus(
        _baostock_code(instrument),
        FIELDS,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        frequency="5",
        adjustflag="3",
    )
    if str(result.error_code) != "0":
        raise RuntimeError(f"{instrument}: {result.error_code} {result.error_msg}")
    # BaoStock stores a complete page in ``result.data``.  Iterating through
    # get_row_data() one row at a time is needlessly slow for a two-year 5m
    # request (tens of thousands of Python calls per symbol).  Advance the
    # page cursor in bulk while retaining the same raw rows and pagination
    # semantics.
    rows: list[list[str]] = []
    if result.data:
        seen_pages: set[tuple[int, str, str]] = set()

        def page_signature() -> tuple[int, str, str]:
            first = "|".join(map(str, result.data[0][:2])) if result.data else ""
            last = "|".join(map(str, result.data[-1][:2])) if result.data else ""
            return len(result.data), first, last

        seen_pages.add(page_signature())
        rows.extend(result.data)
        result.cur_row_num = len(result.data)
        page_count = 1
        while result.next():
            page_count += 1
            signature = page_signature()
            if signature in seen_pages:
                raise RuntimeError(
                    f"{instrument}: BaoStock repeated pagination content at page "
                    f"{result.cur_page_num} ({signature[0]} rows); aborting instead of looping forever"
                )
            if page_count > 1000:
                raise RuntimeError(f"{instrument}: implausible BaoStock pagination depth")
            seen_pages.add(signature)
            rows.extend(result.data)
            result.cur_row_num = len(result.data)
    frame = _normalise_rows(rows, instrument, downloaded_at, start, end)
    if frame.empty:
        raise ValueError(f"{instrument}: BaoStock returned no usable 5-minute rows")
    # A concurrent/aborted page stream can look non-empty while containing
    # only the first 2,000 rows.  Never persist that as a supposedly complete
    # history.  The four-day allowance covers weekends and the provider's
    # latest-session lag; genuinely delisted symbols are recorded as failed
    # rather than silently treated as complete.
    actual_end = frame["datetime"].max().normalize()
    page_size = int(bs_constants.BAOSTOCK_PER_PAGE_COUNT)
    appears_truncated = len(frame) >= page_size and len(frame) % page_size == 0
    if appears_truncated and actual_end < end - pd.Timedelta(days=4):
        raise ValueError(
            f"{instrument}: incomplete 5-minute response through {actual_end.date()} "
            f"(requested {end.date()})"
        )
    return frame


def _set_socket_timeout(seconds: float = 180.0) -> None:
    """Bound a stalled page read so the resumable retry loop can recover."""

    try:
        import baostock.common.context as context

        socket = getattr(context, "default_socket", None)
        if socket is not None:
            socket.settimeout(seconds)
    except Exception:
        # A missing/opaque client socket should not make an otherwise usable
        # BaoStock session fail before the next request.
        pass


def _merge_cached(cached: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if cached.empty:
        return fresh
    combined = pd.concat([cached, fresh], ignore_index=True, sort=False)
    # This directory normally contains only BaoStock rows, but the priority
    # makes a rerun safe if a user manually stages another source here.
    source = combined.get("source", pd.Series("unknown", index=combined.index)).fillna("unknown").astype(str)
    combined["_priority"] = source.map(
        lambda item: 3 if item.startswith("eastmoney") else 2 if item.startswith("baostock") else 1
    )
    combined = (
        combined.sort_values(["instrument", "datetime", "_priority"])
        .drop_duplicates(["instrument", "datetime"], keep="last")
        .drop(columns=["_priority"], errors="ignore")
        .sort_values(["instrument", "datetime"])
        .reset_index(drop=True)
    )
    return combined


def _read_codes_file(path: str) -> set[str]:
    return {
        code
        for code in (normalize_code(item) for item in Path(path).read_text(encoding="utf-8").splitlines())
        if code
    }


def qlib_members_asof(asof: pd.Timestamp) -> set[str]:
    """Return the CSI800 membership interval active on one historical date."""

    import qlib
    from qlib.constant import REG_CN
    from qlib.data import D
    from config import QLIB_DATA_DIR

    qlib.init(provider_uri=str(QLIB_DATA_DIR), region=REG_CN)
    mapping = D.list_instruments(instruments=D.instruments(market="csi800"), as_list=False)
    return {
        normalize_code(instrument) or ""
        for instrument, intervals in mapping.items()
        if any(start.normalize() <= asof <= end.normalize() for start, end in intervals)
    }


def load_codes(universe: str, codes_file: str | None, asof: pd.Timestamp | None = None) -> list[str]:
    if codes_file:
        codes = _read_codes_file(codes_file)
    elif universe == "events":
        codes = local_event_codes()
    elif universe == "csi800_start":
        codes = qlib_members_asof(asof or pd.Timestamp("2026-06-24"))
    else:
        codes = load_universe(universe)
        if universe == "existing":
            codes.update(local_event_codes())
    instruments = {
        instrument_from_code(code)
        for code in codes
        if instrument_from_code(code) is not None
    }
    # BaoStock has SH/SZ coverage; BSE event codes remain in the manifest as
    # skipped unsupported instruments rather than being silently relabeled.
    return sorted(item for item in instruments if item and item[:2] in {"SH", "SZ"})


def _already_covers(path: Path, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    cached = _read_cached(path)
    if cached.empty:
        return False
    minimum = cached["datetime"].min().normalize()
    maximum = cached["datetime"].max().normalize()
    # BaoStock's 5-minute feed can lag the latest trading day.  A max date a
    # few calendar days before the requested end still represents the latest
    # available historical session and should be resumable.
    return minimum <= start and maximum >= end - pd.Timedelta(days=4)


def collect(
    instruments: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    max_codes: int = 0,
    offset: int = 0,
    refresh: bool = False,
    retries: int = 3,
    retry_delay: float = 1.0,
    page_size: int = 10000,
) -> dict[str, Any]:
    selected = instruments[offset : offset + max_codes] if max_codes else instruments[offset:]
    BAOSTOCK_MINUTE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    successes: list[dict[str, Any]] = []
    skipped: list[str] = []
    failures: list[dict[str, str]] = []

    # The provider accepts a larger page than the package default of 2,000;
    # 10,000 is a practical compromise between round trips and response size.
    bs_constants.BAOSTOCK_PER_PAGE_COUNT = max(2000, int(page_size))
    login = bs.login()
    if str(login.error_code) != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    _set_socket_timeout()
    try:
        for number, instrument in enumerate(selected, 1):
            destination = BAOSTOCK_MINUTE_DIR / f"{instrument}.parquet"
            if not refresh and _already_covers(destination, start, end):
                skipped.append(instrument)
                continue
            error: str | None = None
            for attempt in range(1, retries + 1):
                try:
                    downloaded_at = datetime.now().isoformat(timespec="seconds")
                    fresh = _query_symbol(instrument, start, end, downloaded_at)
                    cached = _read_cached(destination)
                    merged = _merge_cached(cached, fresh)
                    _atomic_parquet(merged, destination)
                    successes.append(
                        {
                            "instrument": instrument,
                            "rows": int(len(fresh)),
                            "merged_rows": int(len(merged)),
                            "actual_start": str(fresh["datetime"].min()),
                            "actual_end": str(fresh["datetime"].max()),
                        }
                    )
                    error = None
                    break
                except Exception as exc:
                    error = str(exc)
                    if attempt < retries:
                        try:
                            bs.logout()
                        except Exception:
                            pass
                        time.sleep(retry_delay * attempt)
                        recovery = bs.login()
                        if str(recovery.error_code) != "0":
                            error = f"{error}; reconnect failed: {recovery.error_msg}"
                        else:
                            _set_socket_timeout()
            if error is not None:
                failures.append({"instrument": instrument, "error": error})
            if number == 1 or number % 10 == 0 or number == len(selected):
                print(
                    f"  BaoStock 5m {number}/{len(selected)} "
                    f"downloaded={len(successes)} skipped={len(skipped)} failed={len(failures)}",
                    flush=True,
                )
    finally:
        bs.logout()

    finished = datetime.now(timezone.utc)
    manifest = {
        "provider": "BaoStock",
        "dataset": "equity_5min",
        "config": {
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "frequency": "5",
            "adjustflag": "3",
            "page_size": int(bs_constants.BAOSTOCK_PER_PAGE_COUNT),
            "offset": offset,
            "max_codes": max_codes,
            "refresh": refresh,
        },
        "requested_instruments": len(selected),
        "downloaded": len(successes),
        "skipped_existing": len(skipped),
        "failed": failures,
        "rows": int(sum(item["rows"] for item in successes)),
        "actual_start": min((item["actual_start"] for item in successes), default=None),
        "actual_end": max((item["actual_end"] for item in successes), default=None),
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
        "notes": [
            "BaoStock 5-minute history uses unadjusted adjustflag=3.",
            "The provider is queried serially because anonymous sessions are not safe to parallelize.",
            "BSE/BJ instruments are excluded from the BaoStock request universe.",
        ],
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = MANIFEST_DIR / f"baostock_minute_{stamp}_{os.getpid()}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest: {path}", flush=True)
    return manifest


def parse_args() -> argparse.Namespace:
    today = datetime.now().strftime("%Y%m%d")
    start = (pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=62)).strftime("%Y%m%d")
    parser = argparse.ArgumentParser(description="Serial BaoStock 5-minute backfill")
    parser.add_argument("--start", default=start)
    parser.add_argument("--end", default=today)
    parser.add_argument("--universe", choices=["events", "existing", "csi800", "csi800_start"], default="events")
    parser.add_argument("--codes-file", default=None)
    parser.add_argument("--max-codes", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=1.0)
    parser.add_argument("--page-size", type=int, default=10000)
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    start = _parse_date(args.start)
    end = _parse_date(args.end)
    if end < start:
        raise ValueError("end must be on or after start")
    instruments = load_codes(args.universe, args.codes_file, asof=start)
    print(f"BaoStock minute universe: {len(instruments)} SH/SZ instruments", flush=True)
    return collect(
        instruments,
        start,
        end,
        max_codes=max(0, args.max_codes),
        offset=max(0, args.offset),
        refresh=bool(args.refresh),
        retries=max(1, args.retries),
        retry_delay=max(0.0, args.retry_delay),
        page_size=max(2000, args.page_size),
    )


if __name__ == "__main__":
    main()
