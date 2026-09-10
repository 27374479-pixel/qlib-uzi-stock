from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests


SOURCE = "eastmoney"
SOURCE_DATASET = "security_ann_archive"
SCHEMA_VERSION = "v4.17.2"
PROVIDER_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
DETAIL_URL = "https://data.eastmoney.com/notices/detail"
DEFAULT_ROOT = Path("data_lake/raw/eastmoney/notices")
DEFAULT_MANIFEST_ROOT = Path("data_lake/manifests")
PAGE_SIZE = 100

CANONICAL_COLUMNS = [
    "event_id",
    "schema_version",
    "source",
    "source_dataset",
    "security_code",
    "security_name",
    "notice_title",
    "notice_type",
    "event_date",
    "knowledge_date",
    "timestamp_precision",
    "same_day_usable",
    "source_url",
    "retrieved_at_utc",
    "query_date",
    "date_matches_query",
]


@dataclass
class DayResult:
    query_date: str
    path: str
    rows: int
    status: str
    attempts: int
    pages: int = 0
    error: str | None = None


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_range(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def output_path(root: Path, day: date) -> Path:
    return root / f"{day.year:04d}" / f"{day.isoformat()}.parquet"


def atomic_parquet_write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def empty_frame() -> pd.DataFrame:
    frame = pd.DataFrame(columns=CANONICAL_COLUMNS)
    frame["same_day_usable"] = frame["same_day_usable"].astype("boolean")
    frame["date_matches_query"] = frame["date_matches_query"].astype("boolean")
    return frame


def stable_event_id(code: str, title: str, event_date: str, url: str) -> str:
    raw = "\x1f".join([SOURCE, code, title, event_date, url]).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def request_json(session: requests.Session, params: dict, timeout: float) -> dict:
    response = session.get(PROVIDER_URL, params=params, timeout=(5.0, timeout))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError(f"unexpected Eastmoney response shape: {type(payload).__name__}")
    return payload


def choose_a_share_code(item: dict) -> dict | None:
    codes = item.get("codes") or []
    if len(codes) == 1:
        return codes[0]
    for code in codes:
        if str(code.get("ann_type", "")).startswith("A"):
            return code
    return None


def fetch_raw_eastmoney(day: date, timeout: float) -> tuple[pd.DataFrame, int]:
    iso_day = day.isoformat()
    base_params = {
        "sr": "-1",
        "page_size": str(PAGE_SIZE),
        "page_index": "1",
        "ann_type": "A",
        "client_source": "web",
        "f_node": "0",
        "s_node": "0",
        "begin_time": iso_day,
        "end_time": iso_day,
    }

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; qlib-uzi-stock/1.0; research-data-backfill)",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://data.eastmoney.com/notices/hsa/5.html",
        }
    )

    first = request_json(session, base_params, timeout)
    total_hits = int(first["data"].get("total_hits") or 0)
    total_pages = int(math.ceil(total_hits / PAGE_SIZE)) if total_hits else 0
    if total_pages == 0:
        return pd.DataFrame(columns=["代码", "名称", "公告标题", "公告类型", "公告日期", "网址"]), 0

    rows: list[dict] = []
    for page in range(1, total_pages + 1):
        payload = first if page == 1 else request_json(session, {**base_params, "page_index": str(page)}, timeout)
        items = payload["data"].get("list") or []
        for item in items:
            code = choose_a_share_code(item)
            if not code:
                continue
            columns = item.get("columns") or []
            notice_type = str(columns[0].get("column_name", "")) if columns else ""
            security_code = str(code.get("stock_code", ""))
            art_code = str(item.get("art_code", ""))
            rows.append(
                {
                    "代码": security_code,
                    "名称": str(code.get("short_name", "")),
                    "公告标题": str(item.get("title", "")),
                    "公告类型": notice_type,
                    "公告日期": item.get("notice_date"),
                    "网址": f"{DETAIL_URL}/{security_code}/{art_code}.html" if security_code and art_code else "",
                }
            )

    return pd.DataFrame(rows), total_pages


def normalize_notice_frame(raw: pd.DataFrame, query_day: date, retrieved_at: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return empty_frame()

    expected = {"代码", "名称", "公告标题", "公告类型", "公告日期", "网址"}
    missing = expected.difference(raw.columns)
    if missing:
        raise ValueError(f"unexpected provider schema; missing columns: {sorted(missing)}; got={list(raw.columns)}")

    out = pd.DataFrame()
    out["security_code"] = raw["代码"].astype(str).str.extract(r"(\d+)", expand=False).fillna("").str.zfill(6)
    out["security_name"] = raw["名称"].fillna("").astype(str).str.strip()
    out["notice_title"] = raw["公告标题"].fillna("").astype(str).str.strip()
    out["notice_type"] = raw["公告类型"].fillna("").astype(str).str.strip()
    parsed_date = pd.to_datetime(raw["公告日期"], errors="coerce")
    out["event_date"] = parsed_date.dt.strftime("%Y-%m-%d")
    out["source_url"] = raw["网址"].fillna("").astype(str).str.strip()

    out = out[(out["security_code"] != "") & (out["notice_title"] != "") & out["event_date"].notna()].copy()
    out["schema_version"] = SCHEMA_VERSION
    out["source"] = SOURCE
    out["source_dataset"] = SOURCE_DATASET

    # The archive exposes a calendar date, not a historically trustworthy intraday
    # publication timestamp. We therefore use a deliberately conservative policy:
    # same-day trading is forbidden and downstream research may use the event only
    # when trade_date > knowledge_date.
    out["knowledge_date"] = out["event_date"]
    out["timestamp_precision"] = "day"
    out["same_day_usable"] = False
    out["retrieved_at_utc"] = retrieved_at
    out["query_date"] = query_day.isoformat()
    out["date_matches_query"] = out["event_date"].eq(query_day.isoformat())
    out["event_id"] = [
        stable_event_id(code, title, event_day, url)
        for code, title, event_day, url in zip(
            out["security_code"], out["notice_title"], out["event_date"], out["source_url"]
        )
    ]

    out = out.drop_duplicates(subset=["event_id"], keep="first")
    out = out[CANONICAL_COLUMNS].sort_values(["event_date", "security_code", "event_id"]).reset_index(drop=True)

    if out["event_id"].duplicated().any():
        raise AssertionError("event_id must be unique inside a daily partition")
    if bool(out["same_day_usable"].fillna(True).any()):
        raise AssertionError("day-precision historical notices must never be same-day usable")
    return out


def fetch_day(day: date, retries: int, base_sleep: float, timeout: float) -> tuple[pd.DataFrame, int, int]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            raw, pages = fetch_raw_eastmoney(day, timeout=timeout)
            retrieved_at = datetime.now(timezone.utc).isoformat()
            return normalize_notice_frame(raw, day, retrieved_at), attempt, pages
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                delay = base_sleep * (2 ** (attempt - 1)) + random.uniform(0.0, min(0.5, base_sleep))
                time.sleep(delay)
    assert last_error is not None
    raise last_error


def validate_existing(path: Path) -> int:
    frame = pd.read_parquet(path)
    missing = set(CANONICAL_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"existing partition has stale schema {path}: missing {sorted(missing)}")
    if len(frame) and frame["schema_version"].astype(str).ne(SCHEMA_VERSION).any():
        raise ValueError(f"existing partition has stale schema version {path}")
    if len(frame) and frame["event_id"].duplicated().any():
        raise ValueError(f"duplicate event_id in {path}")
    if len(frame) and bool(frame["same_day_usable"].fillna(True).any()):
        raise ValueError(f"same_day_usable violation in {path}")
    return len(frame)


def collect(args: argparse.Namespace) -> dict:
    start = parse_date(args.start)
    end = parse_date(args.end)
    if end < start:
        raise ValueError("end must be >= start")

    root = Path(args.root)
    manifest_root = Path(args.manifest_root)
    manifest_root.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat()
    results: list[DayResult] = []

    for day in date_range(start, end):
        path = output_path(root, day)
        if path.exists() and not args.force:
            try:
                rows = validate_existing(path)
                results.append(DayResult(day.isoformat(), str(path), rows, "existing", 0))
                continue
            except Exception:
                pass

        try:
            frame, attempts, pages = fetch_day(
                day,
                retries=args.retries,
                base_sleep=args.retry_sleep,
                timeout=args.timeout,
            )
            atomic_parquet_write(frame, path)
            results.append(DayResult(day.isoformat(), str(path), len(frame), "fetched", attempts, pages))
        except Exception as exc:
            results.append(DayResult(day.isoformat(), str(path), 0, "failed", args.retries, 0, repr(exc)))

        if args.request_sleep > 0:
            time.sleep(args.request_sleep)

    failed = [r for r in results if r.status == "failed"]
    fetched_or_existing = [r for r in results if r.status in {"fetched", "existing"}]
    total_rows = sum(r.rows for r in fetched_or_existing)

    nonempty_files = [Path(r.path) for r in fetched_or_existing if r.rows > 0]
    date_match_rows = 0
    checked_rows = 0
    unique_ids: set[str] = set()
    cross_partition_duplicates = 0
    for path in nonempty_files:
        frame = pd.read_parquet(path, columns=["event_id", "date_matches_query"])
        checked_rows += len(frame)
        date_match_rows += int(frame["date_matches_query"].fillna(False).sum())
        for event_id in frame["event_id"].astype(str):
            if event_id in unique_ids:
                cross_partition_duplicates += 1
            unique_ids.add(event_id)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "source_dataset": SOURCE_DATASET,
        "provider_url": PROVIDER_URL,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "point_in_time_policy": {
            "source_time_precision": "day",
            "same_day_usable": False,
            "backtest_rule": "trade_date must be strictly greater than knowledge_date",
            "retrieved_at_is_not_historical_first_seen": True,
            "current_concept_membership_backfill_forbidden": True,
        },
        "days_total": len(results),
        "days_fetched": sum(r.status == "fetched" for r in results),
        "days_existing": sum(r.status == "existing" for r in results),
        "days_failed": len(failed),
        "provider_pages": sum(r.pages for r in results),
        "rows_total": total_rows,
        "rows_checked": checked_rows,
        "date_match_rate": (date_match_rows / checked_rows) if checked_rows else None,
        "cross_partition_duplicate_event_ids": cross_partition_duplicates,
        "results": [asdict(r) for r in results],
    }

    manifest_name = f"v4_17_eastmoney_notices_{start.isoformat()}_{end.isoformat()}.json"
    manifest_path = manifest_root / manifest_name
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, manifest_path)

    print(json.dumps({k: v for k, v in manifest.items() if k != "results"}, ensure_ascii=False, indent=2))
    print(f"manifest={manifest_path}")

    if failed:
        raise SystemExit(f"provider failures on {len(failed)} day(s); see {manifest_path}")
    if cross_partition_duplicates:
        raise SystemExit(f"cross-partition duplicate event ids={cross_partition_duplicates}")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="V4.17 point-in-time Eastmoney A-share notice lake collector")
    p.add_argument("--start", required=True, help="YYYY-MM-DD, inclusive")
    p.add_argument("--end", required=True, help="YYYY-MM-DD, inclusive")
    p.add_argument("--root", default=str(DEFAULT_ROOT))
    p.add_argument("--manifest-root", default=str(DEFAULT_MANIFEST_ROOT))
    p.add_argument("--retries", type=int, default=4)
    p.add_argument("--retry-sleep", type=float, default=1.0)
    p.add_argument("--request-sleep", type=float, default=0.35)
    p.add_argument("--timeout", type=float, default=20.0, help="read timeout seconds per provider request")
    p.add_argument("--force", action="store_true")
    return p


if __name__ == "__main__":
    collect(build_parser().parse_args())
