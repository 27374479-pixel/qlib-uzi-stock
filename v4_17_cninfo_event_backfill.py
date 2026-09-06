from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


PROVIDER = "cninfo"
ENDPOINT = "akshare.stock_zh_a_disclosure_report_cninfo"
SCHEMA_VERSION = "v2"
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
REQUIRED_SOURCE_COLUMNS = {"代码", "简称", "公告标题", "公告时间", "公告链接"}


def parse_date(value: str) -> date:
    return datetime.strptime(value.strip().replace("-", ""), "%Y%m%d").date()


def infer_instrument(code: str) -> tuple[str | None, str]:
    code = str(code).strip().zfill(6)
    if code.startswith(("600", "601", "603", "605", "688")):
        return f"SH{code}", "equity"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return f"SZ{code}", "equity"
    if code.startswith(("43", "83", "87", "88", "92")):
        return f"BJ{code}", "equity"
    return None, "unknown"


def source_event_id_from_url(url: str) -> str:
    text = str(url)
    patterns = [
        r"\b(AN\d{10,})\b",
        r"announcementId[=/](\d{8,})",
        r"announcementId=(\d{8,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def stable_event_id(row: pd.Series) -> str:
    security_code = str(row.get("security_code", ""))
    source_key = str(row.get("source_event_id", "") or "").strip()
    if source_key:
        # event_id is a row-level event-security mapping. source_event_id remains the
        # document-level key so one source document may causally map to multiple stocks.
        raw = f"{PROVIDER}|{source_key}|{security_code}"
    else:
        raw = "|".join(
            [
                PROVIDER,
                security_code,
                str(row.get("published_date", "")),
                str(row.get("title", "")),
                str(row.get("source_url", "")),
            ]
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def load_universe_symbols(path: Path, start: date, end: date) -> list[str]:
    frame = pd.read_csv(path, sep="\t", header=None, names=["instrument", "start_date", "end_date"], dtype=str)
    frame["start_date"] = pd.to_datetime(frame["start_date"], errors="coerce").dt.date
    frame["end_date"] = pd.to_datetime(frame["end_date"], errors="coerce").dt.date
    overlap = frame[(frame["start_date"] <= end) & (frame["end_date"] >= start)].copy()
    symbols = overlap["instrument"].astype(str).str.extract(r"(\d{6})$", expand=False).dropna().unique().tolist()
    return sorted(symbols)


def fetch_symbol(symbol: str, start: date, end: date, max_retries: int, base_sleep: float) -> pd.DataFrame:
    import akshare as ak

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            frame = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=symbol,
                market="沪深京",
                keyword="",
                category="",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            if frame is None:
                return pd.DataFrame(columns=sorted(REQUIRED_SOURCE_COLUMNS))
            missing = REQUIRED_SOURCE_COLUMNS.difference(frame.columns)
            if missing and not frame.empty:
                raise ValueError(f"{symbol}: source schema missing columns: {sorted(missing)}")
            return frame
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= max_retries:
                break
            wait = base_sleep * (2 ** min(attempt, 4)) + random.uniform(0.0, base_sleep)
            time.sleep(wait)
    assert last_error is not None
    raise RuntimeError(f"{symbol}: failed after {max_retries} attempts: {last_error}") from last_error


def normalize_symbol(frame: pd.DataFrame, requested_symbol: str, start: date, end: date, collected_at: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    data = frame.rename(
        columns={
            "代码": "security_code",
            "简称": "security_name",
            "公告标题": "title",
            "公告时间": "published_date",
            "公告链接": "source_url",
        }
    ).copy()

    data["security_code"] = data["security_code"].astype(str).str.extract(r"(\d+)", expand=False).fillna(requested_symbol).str.zfill(6)
    data["security_name"] = data["security_name"].fillna("").astype(str).str.strip()
    data["title"] = data["title"].fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    data["source_url"] = data["source_url"].fillna("").astype(str).str.strip()

    published = pd.to_datetime(data["published_date"], errors="coerce").dt.date
    data["published_date"] = published.map(lambda x: x.isoformat() if pd.notna(x) else "")
    data["eligible_from_date"] = published.map(lambda x: (x + timedelta(days=1)).isoformat() if pd.notna(x) else "")

    inferred = data["security_code"].map(infer_instrument)
    data["instrument"] = inferred.map(lambda x: x[0] or "")
    data["security_type_inferred"] = inferred.map(lambda x: x[1])
    data["source_event_id"] = data["source_url"].map(source_event_id_from_url)
    data["provider"] = PROVIDER
    data["source_endpoint"] = ENDPOINT
    data["schema_version"] = SCHEMA_VERSION
    data["event_type"] = ""
    data["event_time_precision"] = "date"
    data["knowledge_policy"] = "published_date_plus_1_calendar_day"
    data["query_date"] = f"{start.isoformat()}/{end.isoformat()}"
    data["collected_at_utc"] = collected_at
    data["event_id"] = data.apply(stable_event_id, axis=1)

    data = data[
        data["security_code"].str.fullmatch(r"\d{6}", na=False)
        & data["title"].ne("")
        & data["published_date"].ne("")
    ].copy()
    pub = pd.to_datetime(data["published_date"]).dt.date
    data = data[(pub >= start) & (pub <= end)].copy()
    data = data[OUTPUT_COLUMNS].drop_duplicates(subset=["event_id"], keep="first")
    return data.sort_values(["published_date", "event_id"]).reset_index(drop=True)


def merge_symbol_file(path: Path, fresh: pd.DataFrame) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_parquet(path)
        old_rows = len(old)
        old = old.reindex(columns=OUTPUT_COLUMNS)
        combined = pd.concat([old, fresh], ignore_index=True, sort=False)
    else:
        old_rows = 0
        combined = fresh.copy()
    combined = combined.reindex(columns=OUTPUT_COLUMNS)
    combined = combined.drop_duplicates(subset=["event_id"], keep="last")
    combined = combined.sort_values(["published_date", "event_id"]).reset_index(drop=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    combined.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)
    return old_rows, len(combined)


def validate_frame(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    if frame["event_id"].duplicated().any():
        raise AssertionError("duplicate event_id")
    published = pd.to_datetime(frame["published_date"], errors="raise")
    eligible = pd.to_datetime(frame["eligible_from_date"], errors="raise")
    if not (eligible > published).all():
        raise AssertionError("eligible_from_date must be strictly after published_date")
    if not set(frame["event_time_precision"].unique()).issubset({"date"}):
        raise AssertionError("unexpected event_time_precision")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill point-in-time CNINFO notices for the historical research universe.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--symbols", default="", help="Comma-separated 6-digit codes; overrides universe-file.")
    parser.add_argument("--universe-file", default="data_lake/universe/csi800_membership_monthly.tsv")
    parser.add_argument("--output-root", default="data_lake/raw/cninfo/notices")
    parser.add_argument("--manifest-dir", default="data_lake/manifests")
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--sleep-seconds", type=float, default=0.20)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    start = parse_date(args.start_date)
    end = parse_date(args.end_date)
    if end < start:
        raise SystemExit("end-date must be >= start-date")
    if args.shard_count < 1 or not (0 <= args.shard_index < args.shard_count):
        raise SystemExit("invalid shard settings")

    if args.symbols.strip():
        symbols = sorted({s.strip() for s in args.symbols.split(",") if re.fullmatch(r"\d{6}", s.strip())})
    else:
        symbols = load_universe_symbols(Path(args.universe_file), start, end)
    symbols = [s for i, s in enumerate(symbols) if i % args.shard_count == args.shard_index]
    if args.max_symbols > 0:
        symbols = symbols[: args.max_symbols]

    output_root = Path(args.output_root)
    manifest_dir = Path(args.manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    successful: list[dict[str, object]] = []
    failed: list[dict[str, str]] = []
    all_fresh: list[pd.DataFrame] = []

    for idx, symbol in enumerate(symbols, start=1):
        try:
            raw = fetch_symbol(symbol, start, end, args.max_retries, args.sleep_seconds)
            fresh = normalize_symbol(raw, symbol, start, end, collected_at)
            validate_frame(fresh)
            path = output_root / f"{symbol}.parquet"
            old_rows, final_rows = merge_symbol_file(path, fresh)
            successful.append(
                {
                    "symbol": symbol,
                    "fresh_rows": int(len(fresh)),
                    "old_rows": int(old_rows),
                    "final_rows": int(final_rows),
                    "path": path.as_posix(),
                }
            )
            if not fresh.empty:
                all_fresh.append(fresh)
            print(f"[{idx}/{len(symbols)}] {symbol} rows={len(fresh)} final={final_rows}")
        except Exception as exc:
            failed.append({"symbol": symbol, "error": str(exc)})
            print(f"[{idx}/{len(symbols)}] {symbol} FAILED: {exc}")
        time.sleep(max(args.sleep_seconds, 0.0))

    fresh_frame = pd.concat(all_fresh, ignore_index=True) if all_fresh else pd.DataFrame(columns=OUTPUT_COLUMNS)
    validate_frame(fresh_frame)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "provider": PROVIDER,
        "source_endpoint": ENDPOINT,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "universe_file": args.universe_file if not args.symbols.strip() else None,
        "requested_symbols": len(symbols),
        "successful_symbols": len(successful),
        "failed_symbols": failed,
        "fresh_rows": int(len(fresh_frame)),
        "unique_equity_instruments": int(fresh_frame.loc[fresh_frame["instrument"].ne(""), "instrument"].nunique()) if not fresh_frame.empty else 0,
        "shard_count": args.shard_count,
        "shard_index": args.shard_index,
        "collected_at_utc": collected_at,
        "point_in_time_policy": {
            "source_time_precision": "date",
            "eligible_from": "published_date + 1 calendar day",
            "reason": "CNINFO historical output is treated as date-only even if provider internals contain richer timestamps; no intraday availability is inferred.",
            "historical_first_seen": "not claimed; collected_at_utc is ingestion time only",
        },
        "event_identity_policy": {
            "source_event_id": "document-level source identifier when available",
            "event_id": "provider + source document + security mapping; falls back to provider/code/date/title/url",
        },
        "symbols": successful,
    }
    tag = f"s{args.shard_index:03d}of{args.shard_count:03d}"
    manifest_path = manifest_dir / f"cninfo_notices_{start:%Y%m%d}_{end:%Y%m%d}_{tag}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "symbols"}, ensure_ascii=False, indent=2))

    if args.strict and failed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
