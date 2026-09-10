#!/usr/bin/env python3
"""V4.18-A causal event view for date-precision historical announcements.

The canonical V4.17 Eastmoney archive intentionally stores historical
announcements at DATE precision.  It is therefore unsafe to use an event on its
published calendar date for an intraday decision.  This builder materializes the
one downstream field that research actually needs:

    available_trade_date = strictly next frozen A-share trading session

The trading calendar is derived only from already-frozen BaoStock daily equity
files.  No live calendar API, current concept membership, event clustering, or
alpha construction is allowed here.

A V4.17 full-backfill gate whose requested window EXACTLY matches --start/--end
must PASS before this builder will run.  This prevents a one-day smoke PASS from
unlocking a multi-year research window.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

VIEW_VERSION = "v4.18-a.1"
REQUIRED_GATE_VERSION_PREFIX = "v4.17-c."
CANONICAL_SCHEMA_VERSION = "v4.17-a.2"
CANONICAL_SOURCE_PROVIDER = "eastmoney"
CANONICAL_SOURCE_ENDPOINT = "akshare.stock_notice_report"
CANONICAL_EVENT_TYPE = "corporate_announcement"
CANONICAL_CAUSAL_POLICY = "NEXT_TRADING_DAY_ONLY"
DATE_COLUMN_CANDIDATES = ("date", "trade_date", "datetime", "time")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="event window start YYYY-MM-DD inclusive")
    p.add_argument("--end", required=True, help="event window end YYYY-MM-DD inclusive")
    p.add_argument("--event-root", default="data_lake/raw/eastmoney/notices")
    p.add_argument("--daily-root", default="data_lake/raw/baostock/equity_daily")
    p.add_argument("--v417-gate", default="output/v4_17_full_backfill_gate.json")
    p.add_argument(
        "--research-end",
        default=None,
        help=(
            "optional last trading date research may consume; events whose next "
            "session is later are marked OUT_OF_RESEARCH_HORIZON"
        ),
    )
    p.add_argument("--min-active-instruments", type=int, default=100)
    p.add_argument(
        "--output",
        default="data_lake/derived/v4_18_causal_events/events.parquet",
    )
    p.add_argument(
        "--manifest",
        default="output/v4_18_causal_event_view_manifest.json",
    )
    return p.parse_args()


def load_gate(path: Path, start: date, end: date) -> dict:
    if not path.exists():
        raise SystemExit(f"missing V4.17 full-backfill gate: {path}")
    try:
        gate = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"cannot parse V4.17 gate {path}: {exc}") from exc

    failures: list[str] = []
    gate_version = str(gate.get("gate_version", ""))
    if not gate_version.startswith(REQUIRED_GATE_VERSION_PREFIX):
        failures.append(f"unsupported V4.17 gate version: {gate_version!r}")
    if gate.get("requested_start") != start.isoformat():
        failures.append(
            f"gate requested_start={gate.get('requested_start')!r} != {start.isoformat()!r}"
        )
    if gate.get("requested_end") != end.isoformat():
        failures.append(
            f"gate requested_end={gate.get('requested_end')!r} != {end.isoformat()!r}"
        )
    if not bool(gate.get("validation", {}).get("pass", False)):
        failures.append("V4.17 gate validation.pass is not true")
    if not bool(gate.get("research_eligibility", {}).get("h04_h05_allowed", False)):
        failures.append("V4.17 gate does not allow downstream causal research")
    completion = gate.get("completion", {})
    if completion.get("failed_years"):
        failures.append(f"V4.17 gate still has failed years: {completion.get('failed_years')}")

    if failures:
        raise SystemExit("V4.18 refused stale/incomplete V4.17 gate: " + "; ".join(failures))
    return gate


def iter_year_partitions(root: Path, start: date, end: date):
    for year in range(start.year, end.year + 1):
        path = root / f"year={year}" / f"notices_{year}.parquet"
        if not path.exists():
            raise SystemExit(f"missing canonical V4.17 event partition: {path}")
        yield path


def load_events(root: Path, start: date, end: date) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    required = {
        "schema_version",
        "event_id",
        "source_provider",
        "source_endpoint",
        "event_type",
        "published_date",
        "timestamp_precision",
        "instrument",
        "causal_use_policy",
    }

    for path in iter_year_partitions(root, start, end):
        frame = pd.read_parquet(path)
        missing = required - set(frame.columns)
        if missing:
            raise SystemExit(f"{path}: missing canonical columns {sorted(missing)}")
        frames.append(frame)

    if not frames:
        return pd.DataFrame()

    events = pd.concat(frames, ignore_index=True)
    published = pd.to_datetime(events["published_date"], errors="coerce")
    if published.isna().any():
        raise SystemExit(f"unparseable published_date rows: {int(published.isna().sum())}")
    pub_date = published.dt.date
    events = events[(pub_date >= start) & (pub_date <= end)].copy()

    checks = {
        "schema_version": events["schema_version"].astype(str).eq(CANONICAL_SCHEMA_VERSION),
        "source_provider": events["source_provider"].astype(str).eq(CANONICAL_SOURCE_PROVIDER),
        "source_endpoint": events["source_endpoint"].astype(str).eq(CANONICAL_SOURCE_ENDPOINT),
        "event_type": events["event_type"].astype(str).eq(CANONICAL_EVENT_TYPE),
        "timestamp_precision": events["timestamp_precision"].astype(str).eq("date"),
        "causal_use_policy": events["causal_use_policy"].astype(str).eq(CANONICAL_CAUSAL_POLICY),
    }
    violations = {name: int((~mask).sum()) for name, mask in checks.items() if not mask.all()}
    if violations:
        raise SystemExit(f"noncanonical V4.17 rows reached V4.18: {violations}")
    if events["event_id"].duplicated().any():
        raise SystemExit(
            f"duplicate event_id reached V4.18: {int(events['event_id'].duplicated().sum())}"
        )

    events["published_date"] = pd.to_datetime(events["published_date"]).dt.date.astype(str)
    return events.sort_values(["published_date", "instrument", "event_id"]).reset_index(drop=True)


def _looks_like_lfs_pointer(path: Path) -> bool:
    try:
        if path.stat().st_size > 512:
            return False
        head = path.read_bytes()[:200]
        return b"git-lfs.github.com/spec/v1" in head
    except OSError:
        return False


def _date_column(path: Path) -> str | None:
    schema_names = set(pq.ParquetFile(path).schema.names)
    for candidate in DATE_COLUMN_CANDIDATES:
        if candidate in schema_names:
            return candidate
    return None


def build_frozen_calendar(
    daily_root: Path,
    min_active_instruments: int,
) -> tuple[list[date], dict]:
    if min_active_instruments < 1:
        raise SystemExit("--min-active-instruments must be >= 1")
    if not daily_root.exists():
        raise SystemExit(f"missing BaoStock daily root: {daily_root}")

    files = sorted(daily_root.glob("*.parquet"))
    if not files:
        raise SystemExit(f"no BaoStock daily parquet files found under {daily_root}")

    active = Counter()
    incompatible: list[str] = []
    lfs_pointers: list[str] = []
    readable_files = 0

    for path in files:
        if _looks_like_lfs_pointer(path):
            lfs_pointers.append(str(path))
            continue
        try:
            col = _date_column(path)
            if col is None:
                incompatible.append(str(path))
                continue
            frame = pd.read_parquet(path, columns=[col])
            values = pd.to_datetime(frame[col], errors="coerce").dropna().dt.date.unique()
            for day in values:
                active[day] += 1
            readable_files += 1
        except Exception as exc:
            incompatible.append(f"{path}: {type(exc).__name__}: {exc}")

    if lfs_pointers:
        sample = ", ".join(lfs_pointers[:3])
        raise SystemExit(
            "BaoStock files are Git LFS pointers rather than parquet content; "
            f"materialize LFS before V4.18 (examples: {sample})"
        )
    if readable_files == 0:
        raise SystemExit("no readable BaoStock daily files available for frozen calendar")

    sessions = sorted(day for day, count in active.items() if count >= min_active_instruments)
    if not sessions:
        raise SystemExit(
            "no market sessions satisfy --min-active-instruments="
            f"{min_active_instruments}; max observed active instruments="
            f"{max(active.values(), default=0)}"
        )

    date_lines = "\n".join(d.isoformat() for d in sessions)
    calendar_hash = hashlib.sha256(date_lines.encode("utf-8")).hexdigest()
    diagnostics = {
        "source_root": str(daily_root),
        "parquet_files_seen": len(files),
        "readable_files": readable_files,
        "incompatible_files": incompatible[:50],
        "incompatible_file_count": len(incompatible),
        "min_active_instruments": min_active_instruments,
        "max_active_instruments": int(max(active.values(), default=0)),
        "session_count": len(sessions),
        "first_session": sessions[0].isoformat(),
        "last_session": sessions[-1].isoformat(),
        "calendar_sha256": calendar_hash,
    }
    return sessions, diagnostics


def next_session(sessions: list[date], published: date) -> date | None:
    idx = bisect.bisect_right(sessions, published)
    if idx >= len(sessions):
        return None
    return sessions[idx]


def materialize_availability(
    events: pd.DataFrame,
    sessions: list[date],
    calendar_hash: str,
    research_end: date | None,
) -> tuple[pd.DataFrame, dict]:
    out = events.copy()
    available: list[str | None] = []
    statuses: list[str] = []

    for raw_day in out["published_date"].astype(str):
        published = date.fromisoformat(raw_day)
        nxt = next_session(sessions, published)
        if nxt is None:
            available.append(None)
            statuses.append("NO_NEXT_SESSION_IN_FROZEN_CALENDAR")
        elif research_end is not None and nxt > research_end:
            available.append(None)
            statuses.append("OUT_OF_RESEARCH_HORIZON")
        else:
            available.append(nxt.isoformat())
            statuses.append("AVAILABLE_NEXT_SESSION")

    out["available_trade_date"] = available
    out["causal_status"] = statuses
    out["availability_rule_version"] = VIEW_VERSION
    out["calendar_sha256"] = calendar_hash

    bad_same_day = 0
    for pub, avail in zip(out["published_date"].astype(str), out["available_trade_date"]):
        if pd.notna(avail) and date.fromisoformat(str(avail)) <= date.fromisoformat(pub):
            bad_same_day += 1
    if bad_same_day:
        raise SystemExit(
            f"causal violation: {bad_same_day} rows have available_trade_date <= published_date"
        )

    counts = {str(k): int(v) for k, v in out["causal_status"].value_counts().items()}
    metrics = {
        "event_rows": int(len(out)),
        "unique_events": int(out["event_id"].nunique()),
        "unique_instruments": int(out["instrument"].nunique()),
        "status_counts": counts,
        "same_day_or_earlier_violations": bad_same_day,
    }
    return out, metrics


def main() -> None:
    args = parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end must be >= --start")
    research_end = date.fromisoformat(args.research_end) if args.research_end else None
    if research_end is not None and research_end < start:
        raise SystemExit("--research-end must be >= --start")

    gate_path = Path(args.v417_gate)
    gate = load_gate(gate_path, start, end)
    events = load_events(Path(args.event_root), start, end)
    sessions, calendar_diag = build_frozen_calendar(
        Path(args.daily_root), args.min_active_instruments
    )
    causal, event_metrics = materialize_availability(
        events,
        sessions,
        calendar_diag["calendar_sha256"],
        research_end,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    causal.to_parquet(output_path, index=False)

    manifest = {
        "view_version": VIEW_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "research_end": research_end.isoformat() if research_end else None,
        "upstream_v417_gate": {
            "path": str(gate_path),
            "gate_version": gate.get("gate_version"),
            "requested_start": gate.get("requested_start"),
            "requested_end": gate.get("requested_end"),
            "pass": bool(gate.get("validation", {}).get("pass", False)),
            "h04_h05_allowed": bool(
                gate.get("research_eligibility", {}).get("h04_h05_allowed", False)
            ),
        },
        "calendar": calendar_diag,
        "availability_contract": {
            "source_event_precision": "date",
            "source_causal_policy": CANONICAL_CAUSAL_POLICY,
            "rule": "strictly next frozen A-share trading session after published_date",
            "same_day_use_allowed": False,
            "intraday_timestamp_fabricated": False,
            "live_calendar_api_used": False,
        },
        "events": event_metrics,
        "output": str(output_path),
        "validation": {
            "pass": event_metrics["same_day_or_earlier_violations"] == 0,
            "failures": [],
        },
    }

    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
