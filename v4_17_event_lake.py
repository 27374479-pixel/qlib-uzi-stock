from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


SOURCE = "eastmoney"
ENDPOINT = "akshare.stock_notice_report"
SCHEMA_VERSION = "v1"
REQUIRED_SOURCE_COLUMNS = {"代码", "名称", "公告标题", "公告类型", "公告日期", "网址"}
OUTPUT_COLUMNS = [
    "event_id",
    "source_event_id",
    "provider",
    "source_endpoint",
    "schema_version",
    "security_code",
    "instrument",
    "security_name",
    "security_type_inferred",
    "event_type",
    "title",
    "source_url",
    "published_date",
    "eligible_from_date",
    "event_time_precision",
    "knowledge_policy",
    "query_date",
    "collected_at_utc",
]


def parse_date(value: str) -> date:
    value = value.strip().replace("-", "")
    return datetime.strptime(value, "%Y%m%d").date()


def iter_dates(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def infer_instrument(code: str) -> tuple[str | None, str]:
    """Infer A-share exchange conservatively; leave non-equities unmapped."""
    code = str(code).strip().zfill(6)
    if code.startswith(("600", "601", "603", "605", "688")):
        return f"SH{code}", "equity"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return f"SZ{code}", "equity"
    # Beijing Stock Exchange historical/new code families. Keep inference explicit.
    if code.startswith(("43", "83", "87", "88", "92")):
        return f"BJ{code}", "equity"
    return None, "unknown"


def source_event_id_from_url(url: str) -> str:
    match = re.search(r"\b(AN\d{10,})\b", str(url), flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def stable_event_id(row: pd.Series) -> str:
    source_key = str(row.get("source_event_id", "") or "").strip()
    if source_key:
        raw = f"{SOURCE}|{source_key}"
    else:
        raw = "|".join(
            [
                SOURCE,
                str(row.get("security_code", "")),
                str(row.get("published_date", "")),
                str(row.get("event_type", "")),
                str(row.get("title", "")),
                str(row.get("source_url", "")),
            ]
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def empty_output_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def fetch_notice_day(day: date, symbol: str, max_retries: int, base_sleep: float) -> pd.DataFrame:
    import akshare as ak

    ymd = day.strftime("%Y%m%d")
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            frame = ak.stock_notice_report(symbol=symbol, date=ymd)
            if frame is None:
                return pd.DataFrame(columns=sorted(REQUIRED_SOURCE_COLUMNS))
            missing = REQUIRED_SOURCE_COLUMNS.difference(frame.columns)
            if missing and not frame.empty:
                raise ValueError(f"{ymd}: source schema missing columns: {sorted(missing)}")
            return frame
        except Exception as exc:  # provider/network failures are retried and surfaced in manifest
            last_error = exc
            if attempt + 1 >= max_retries:
                break
            sleep_for = base_sleep * (2 ** min(attempt, 4)) + random.uniform(0.0, base_sleep)
            time.sleep(sleep_for)
    assert last_error is not None
    raise RuntimeError(f"{ymd}: failed after {max_retries} attempts: {last_error}") from last_error


def normalize_notice_day(frame: pd.DataFrame, query_day: date, collected_at: str) -> pd.DataFrame:
    if frame.empty:
        return empty_output_frame()

    data = frame.rename(
        columns={
            "代码": "security_code",
            "名称": "security_name",
            "公告标题": "title",
            "公告类型": "event_type",
            "公告日期": "published_date",
            "网址": "source_url",
        }
    ).copy()

    data["security_code"] = data["security_code"].astype(str).str.extract(r"(\d+)", expand=False).fillna("").str.zfill(6)
    data["security_name"] = data["security_name"].fillna("").astype(str).str.strip()
    data["title"] = data["title"].fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    data["event_type"] = data["event_type"].fillna("").astype(str).str.strip()
    data["source_url"] = data["source_url"].fillna("").astype(str).str.strip()

    published = pd.to_datetime(data["published_date"], errors="coerce").dt.date
    data["published_date"] = published.map(lambda x: x.isoformat() if pd.notna(x) else "")
    data["eligible_from_date"] = published.map(
        lambda x: (x + timedelta(days=1)).isoformat() if pd.notna(x) else ""
    )

    inferred = data["security_code"].map(infer_instrument)
    data["instrument"] = inferred.map(lambda x: x[0] or "")
    data["security_type_inferred"] = inferred.map(lambda x: x[1])
    data["source_event_id"] = data["source_url"].map(source_event_id_from_url)
    data["provider"] = SOURCE
    data["source_endpoint"] = ENDPOINT
    data["schema_version"] = SCHEMA_VERSION
    data["event_time_precision"] = "date"
    data["knowledge_policy"] = "published_date_plus_1_calendar_day"
    data["query_date"] = query_day.isoformat()
    data["collected_at_utc"] = collected_at
    data["event_id"] = data.apply(stable_event_id, axis=1)

    # Drop malformed rows rather than silently treating them as causal events.
    data = data[
        data["security_code"].str.fullmatch(r"\d{6}", na=False)
        & data["title"].ne("")
        & data["published_date"].ne("")
    ].copy()

    data = data[OUTPUT_COLUMNS].drop_duplicates(subset=["event_id"], keep="first")
    return data.sort_values(["published_date", "security_code", "event_id"]).reset_index(drop=True)


def partition_path(root: Path, year: int, month: int) -> Path:
    return root / f"{year:04d}" / f"{month:02d}.parquet"


def merge_partition(path: Path, fresh: pd.DataFrame) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    old_rows = 0
    if path.exists():
        old = pd.read_parquet(path)
        old_rows = len(old)
        combined = pd.concat([old, fresh], ignore_index=True, sort=False)
    else:
        combined = fresh.copy()

    combined = combined[OUTPUT_COLUMNS].drop_duplicates(subset=["event_id"], keep="last")
    combined = combined.sort_values(["published_date", "security_code", "event_id"]).reset_index(drop=True)

    tmp = path.with_suffix(path.suffix + ".tmp")
    combined.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)
    return old_rows, len(combined)


def validate_output(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    if frame["event_id"].duplicated().any():
        raise AssertionError("event_id must be unique within the run")
    published = pd.to_datetime(frame["published_date"], errors="raise")
    eligible = pd.to_datetime(frame["eligible_from_date"], errors="raise")
    if not (eligible > published).all():
        raise AssertionError("eligible_from_date must be strictly after published_date")
    if frame["title"].eq("").any():
        raise AssertionError("title must not be empty")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build point-in-time Eastmoney A-share announcement event lake.")
    parser.add_argument("--start-date", required=True, help="YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--symbol", default="全部", choices=["全部", "重大事项", "财务报告", "融资公告", "风险提示", "资产重组", "信息变更", "持股变动"])
    parser.add_argument("--output-root", default="data_lake/raw/eastmoney/notices")
    parser.add_argument("--manifest-dir", default="data_lake/manifests")
    parser.add_argument("--max-retries", type=int, default=6)
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument("--strict", action="store_true", help="Return non-zero when any requested date failed.")
    args = parser.parse_args()

    start = parse_date(args.start_date)
    end = parse_date(args.end_date)
    if end < start:
        raise SystemExit("end-date must be >= start-date")

    output_root = Path(args.output_root)
    manifest_dir = Path(args.manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    requested_days = list(iter_dates(start, end))
    successful_days: list[str] = []
    empty_days: list[str] = []
    failed_days: list[dict[str, str]] = []
    frames: list[pd.DataFrame] = []

    for idx, day in enumerate(requested_days, start=1):
        try:
            raw = fetch_notice_day(day, args.symbol, args.max_retries, args.sleep_seconds)
            normalized = normalize_notice_day(raw, day, collected_at)
            successful_days.append(day.isoformat())
            if normalized.empty:
                empty_days.append(day.isoformat())
            else:
                frames.append(normalized)
            print(f"[{idx}/{len(requested_days)}] {day.isoformat()} rows={len(normalized)}")
        except Exception as exc:
            failed_days.append({"date": day.isoformat(), "error": str(exc)})
            print(f"[{idx}/{len(requested_days)}] {day.isoformat()} FAILED: {exc}")
        time.sleep(max(args.sleep_seconds, 0.0))

    run_frame = pd.concat(frames, ignore_index=True) if frames else empty_output_frame()
    if not run_frame.empty:
        run_frame = run_frame.drop_duplicates(subset=["event_id"], keep="last").reset_index(drop=True)
    validate_output(run_frame)

    partition_updates: list[dict[str, object]] = []
    if not run_frame.empty:
        run_frame["_partition"] = pd.to_datetime(run_frame["published_date"]).dt.strftime("%Y-%m")
        for part, part_frame in run_frame.groupby("_partition", sort=True):
            year, month = map(int, str(part).split("-"))
            path = partition_path(output_root, year, month)
            fresh = part_frame.drop(columns=["_partition"])
            old_rows, new_rows = merge_partition(path, fresh)
            partition_updates.append(
                {
                    "partition": str(part),
                    "path": path.as_posix(),
                    "fresh_rows": int(len(fresh)),
                    "old_rows": int(old_rows),
                    "final_rows": int(new_rows),
                }
            )

    equity_rows = int((run_frame.get("security_type_inferred", pd.Series(dtype=str)) == "equity").sum()) if not run_frame.empty else 0
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "provider": SOURCE,
        "source_endpoint": ENDPOINT,
        "symbol": args.symbol,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "requested_days": len(requested_days),
        "successful_days": len(successful_days),
        "empty_days": len(empty_days),
        "failed_days": failed_days,
        "run_rows": int(len(run_frame)),
        "equity_rows_inferred": equity_rows,
        "unique_security_codes": int(run_frame["security_code"].nunique()) if not run_frame.empty else 0,
        "unique_equity_instruments": int(run_frame.loc[run_frame["instrument"].ne(""), "instrument"].nunique()) if not run_frame.empty else 0,
        "partition_updates": partition_updates,
        "collected_at_utc": collected_at,
        "point_in_time_policy": {
            "source_time_precision": "date",
            "eligible_from": "published_date + 1 calendar day",
            "reason": "Never infer an intraday publication time from a date-only historical endpoint.",
            "historical_first_seen": "not claimed; collected_at_utc is ingestion time only",
        },
    }
    manifest_path = manifest_dir / f"eastmoney_notices_{start:%Y%m%d}_{end:%Y%m%d}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if args.strict and failed_days:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
