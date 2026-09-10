#!/usr/bin/env python3
"""V4.17-C full-backfill completion and canonical-writer gate.

This is the final machine gate before H04/H05 may consume the Eastmoney
announcement archive.  It proves both calendar completeness and that every row
was materialized with the one canonical V4.17-A identity/schema contract.

Historical Eastmoney rows are DATE precision.  The raw lake MUST NOT fabricate
an intraday availability timestamp; downstream research derives a strictly-next
A-share trading-session ``available_trade_date`` from the frozen market
calendar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

GATE_VERSION = "v4.17-c.2"
CANONICAL_SCHEMA_VERSION = "v4.17-a.2"
CANONICAL_SOURCE_PROVIDER = "eastmoney"
CANONICAL_SOURCE_ENDPOINT = "akshare.stock_notice_report"
CANONICAL_EVENT_TYPE = "corporate_announcement"
CANONICAL_CAUSAL_POLICY = "NEXT_TRADING_DAY_ONLY"
TERMINAL_STATUSES = {"success", "empty"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

FORBIDDEN_RAW_THEME_COLUMNS = {
    "theme_id",
    "theme_name",
    "concept_id",
    "concept_code",
    "concept_name",
    "concept_membership",
    "current_concept",
}

REQUIRED_EVENT_COLUMNS = {
    "schema_version",
    "event_id",
    "source_provider",
    "source_endpoint",
    "event_type",
    "archive_request_date",
    "published_date",
    "published_at",
    "timestamp_precision",
    "stock_code_raw",
    "instrument",
    "stock_name",
    "title",
    "announcement_type",
    "source_url",
    "retrieved_at",
    "first_seen_at",
    "causal_use_policy",
    "raw_payload_hash",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="YYYY-MM-DD inclusive")
    p.add_argument("--end", required=True, help="YYYY-MM-DD inclusive")
    p.add_argument("--event-root", default="data_lake/raw/eastmoney/notices")
    p.add_argument("--manifest-root", default="data_lake/manifests")
    p.add_argument(
        "--validation",
        default="output/v4_17_event_lake_validation.json",
        help="row-level validator report that must already PASS",
    )
    p.add_argument("--output", default="output/v4_17_full_backfill_gate.json")
    p.add_argument("--min-source-url-coverage", type=float, default=0.99)
    return p.parse_args()


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def year_window(year: int, start: date, end: date) -> tuple[date, date]:
    return max(start, date(year, 1, 1)), min(end, date(year, 12, 31))


def add_failure(failures: list[str], condition: bool, message: str) -> None:
    if condition:
        failures.append(message)


def load_upstream_validation(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"missing upstream validation report: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"cannot parse upstream validation report {path}: {exc}") from exc


def latest_ledger_rows(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"request_date": str})
    required = {"request_date", "status", "retrieved_at"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing ledger columns {sorted(missing)}")
    return (
        df.sort_values(["request_date", "retrieved_at"])
        .drop_duplicates("request_date", keep="last")
        .copy()
    )


def canonical_event_id(row: pd.Series) -> str:
    """Recompute the identity defined by the canonical V4.17-A collector."""
    identity = "|".join(
        [
            CANONICAL_SOURCE_PROVIDER,
            str(row["published_date"]),
            str(row["stock_code_raw"]),
            str(row["title"]),
            str(row["source_url"]),
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def validate_year(
    year: int,
    start: date,
    end: date,
    event_root: Path,
    manifest_root: Path,
    min_source_url_coverage: float,
) -> dict:
    ystart, yend = year_window(year, start, end)
    expected_dates = {d.isoformat() for d in daterange(ystart, yend)}
    parquet_path = event_root / f"year={year}" / f"notices_{year}.parquet"
    ledger_path = manifest_root / f"v4_17_eastmoney_notice_requests_{year}.csv"
    failures: list[str] = []

    add_failure(failures, not parquet_path.exists(), f"missing event partition: {parquet_path}")
    add_failure(failures, not ledger_path.exists(), f"missing request ledger: {ledger_path}")

    if ledger_path.exists():
        ledger = latest_ledger_rows(ledger_path)
        parsed = pd.to_datetime(ledger["request_date"], errors="coerce").dt.date
        window_ledger = ledger[(parsed >= ystart) & (parsed <= yend)].copy()
        observed_dates = set(window_ledger["request_date"].astype(str))
        missing_dates = sorted(expected_dates - observed_dates)
        unresolved = window_ledger[window_ledger["status"] == "error"]
        unexpected = window_ledger[~window_ledger["status"].isin(TERMINAL_STATUSES)]
        terminal_dates = set(
            window_ledger.loc[
                window_ledger["status"].isin(TERMINAL_STATUSES), "request_date"
            ].astype(str)
        )
        incomplete_dates = sorted(expected_dates - terminal_dates)
        add_failure(failures, bool(missing_dates), f"missing request dates: {missing_dates[:20]}")
        add_failure(failures, not unresolved.empty, f"unresolved provider errors: {len(unresolved)}")
        add_failure(failures, not unexpected.empty, f"unexpected request statuses: {len(unexpected)}")
        add_failure(failures, bool(incomplete_dates), f"non-terminal dates: {incomplete_dates[:20]}")
        status_counts = {
            str(k): int(v)
            for k, v in window_ledger["status"].value_counts(dropna=False).items()
        }
    else:
        window_ledger = pd.DataFrame()
        missing_dates = sorted(expected_dates)
        incomplete_dates = sorted(expected_dates)
        unresolved = pd.DataFrame()
        status_counts = {}

    metrics = {
        "event_rows": 0,
        "unique_events": 0,
        "unique_instruments": 0,
        "source_url_coverage": 0.0,
        "min_published_date": None,
        "max_published_date": None,
        "invalid_event_id_format": 0,
        "event_id_identity_mismatches": 0,
        "semantic_duplicate_rows": 0,
        "noncanonical_schema_rows": 0,
        "noncanonical_source_rows": 0,
        "noncanonical_endpoint_rows": 0,
        "noncanonical_event_type_rows": 0,
        "forbidden_raw_theme_columns_present": [],
    }

    if parquet_path.exists():
        events = pd.read_parquet(parquet_path)
        missing_cols = REQUIRED_EVENT_COLUMNS - set(events.columns)
        add_failure(failures, bool(missing_cols), f"missing event columns: {sorted(missing_cols)}")

        forbidden_present = sorted(FORBIDDEN_RAW_THEME_COLUMNS & set(events.columns))
        metrics["forbidden_raw_theme_columns_present"] = forbidden_present
        add_failure(
            failures,
            bool(forbidden_present),
            "derived/current theme columns leaked into raw archive: " + ", ".join(forbidden_present),
        )

        if not missing_cols:
            pub = pd.to_datetime(events["published_date"], errors="coerce").dt.date
            in_window = events[(pub >= ystart) & (pub <= yend)].copy()
            metrics["event_rows"] = int(len(in_window))
            metrics["unique_events"] = int(in_window["event_id"].nunique())
            metrics["unique_instruments"] = int(in_window["instrument"].nunique())
            metrics["min_published_date"] = (
                str(in_window["published_date"].min()) if not in_window.empty else None
            )
            metrics["max_published_date"] = (
                str(in_window["published_date"].max()) if not in_window.empty else None
            )

            if not in_window.empty:
                metrics["source_url_coverage"] = float(
                    in_window["source_url"].fillna("").astype(str).str.strip().ne("").mean()
                )
                add_failure(
                    failures,
                    metrics["source_url_coverage"] < min_source_url_coverage,
                    f"source URL coverage {metrics['source_url_coverage']:.6f} < {min_source_url_coverage:.6f}",
                )

                duplicate_ids = int(in_window["event_id"].duplicated().sum())
                add_failure(failures, duplicate_ids > 0, f"duplicate event_id within year: {duplicate_ids}")

                event_ids = in_window["event_id"].fillna("").astype(str)
                metrics["invalid_event_id_format"] = int((~event_ids.str.match(SHA256_RE)).sum())
                add_failure(
                    failures,
                    metrics["invalid_event_id_format"] > 0,
                    f"noncanonical event_id format rows: {metrics['invalid_event_id_format']}",
                )

                expected_ids = in_window.apply(canonical_event_id, axis=1)
                metrics["event_id_identity_mismatches"] = int((event_ids != expected_ids).sum())
                add_failure(
                    failures,
                    metrics["event_id_identity_mismatches"] > 0,
                    "event_id does not match canonical provider|date|code|title|url identity: "
                    f"{metrics['event_id_identity_mismatches']} rows",
                )

                semantic_columns = [
                    "source_provider",
                    "published_date",
                    "stock_code_raw",
                    "title",
                    "source_url",
                ]
                metrics["semantic_duplicate_rows"] = int(
                    in_window.duplicated(semantic_columns, keep=False).sum()
                )
                add_failure(
                    failures,
                    metrics["semantic_duplicate_rows"] > 0,
                    f"semantic duplicate announcement rows: {metrics['semantic_duplicate_rows']}",
                )

                metrics["noncanonical_schema_rows"] = int(
                    in_window["schema_version"].astype(str).ne(CANONICAL_SCHEMA_VERSION).sum()
                )
                metrics["noncanonical_source_rows"] = int(
                    in_window["source_provider"].astype(str).ne(CANONICAL_SOURCE_PROVIDER).sum()
                )
                metrics["noncanonical_endpoint_rows"] = int(
                    in_window["source_endpoint"].astype(str).ne(CANONICAL_SOURCE_ENDPOINT).sum()
                )
                metrics["noncanonical_event_type_rows"] = int(
                    in_window["event_type"].astype(str).ne(CANONICAL_EVENT_TYPE).sum()
                )
                add_failure(
                    failures,
                    metrics["noncanonical_schema_rows"] > 0,
                    f"noncanonical schema rows: {metrics['noncanonical_schema_rows']}",
                )
                add_failure(
                    failures,
                    metrics["noncanonical_source_rows"] > 0,
                    f"noncanonical source rows: {metrics['noncanonical_source_rows']}",
                )
                add_failure(
                    failures,
                    metrics["noncanonical_endpoint_rows"] > 0,
                    f"noncanonical endpoint rows: {metrics['noncanonical_endpoint_rows']}",
                )
                add_failure(
                    failures,
                    metrics["noncanonical_event_type_rows"] > 0,
                    f"noncanonical event_type rows: {metrics['noncanonical_event_type_rows']}",
                )

                date_rows = in_window[in_window["timestamp_precision"] == "date"]
                add_failure(
                    failures,
                    len(date_rows) != len(in_window),
                    "canonical Eastmoney archive must be entirely date precision",
                )
                add_failure(
                    failures,
                    not date_rows["published_at"].isna().all(),
                    "date-precision rows fabricated published_at",
                )
                add_failure(
                    failures,
                    not date_rows["first_seen_at"].isna().all(),
                    "date-precision rows fabricated first_seen_at",
                )
                add_failure(
                    failures,
                    not date_rows["causal_use_policy"].eq(CANONICAL_CAUSAL_POLICY).all(),
                    "date-precision rows are not strictly NEXT_TRADING_DAY_ONLY",
                )

    return {
        "year": year,
        "requested_start": ystart.isoformat(),
        "requested_end": yend.isoformat(),
        "expected_calendar_days": len(expected_dates),
        "observed_request_days": int(len(window_ledger)),
        "terminal_request_days": int(len(expected_dates) - len(incomplete_dates)),
        "status_counts": status_counts,
        "missing_request_dates": missing_dates,
        "incomplete_request_dates": incomplete_dates,
        "unresolved_error_dates": (
            unresolved["request_date"].astype(str).tolist() if not unresolved.empty else []
        ),
        "event_partition": str(parquet_path),
        "manifest": str(ledger_path),
        **metrics,
        "pass": not failures,
        "failures": failures,
    }


def main() -> None:
    args = parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end must be >= --start")
    if not (0.0 <= args.min_source_url_coverage <= 1.0):
        raise SystemExit("--min-source-url-coverage must be in [0, 1]")

    event_root = Path(args.event_root)
    manifest_root = Path(args.manifest_root)
    upstream_path = Path(args.validation)
    upstream = load_upstream_validation(upstream_path)

    failures: list[str] = []
    upstream_pass = bool(upstream.get("validation", {}).get("pass", False))
    add_failure(failures, not upstream_pass, "upstream row-level V4.17 validation did not PASS")
    add_failure(
        failures,
        upstream.get("requested_start") != start.isoformat(),
        "upstream validation start does not match gate window",
    )
    add_failure(
        failures,
        upstream.get("requested_end") != end.isoformat(),
        "upstream validation end does not match gate window",
    )

    years = list(range(start.year, end.year + 1))
    yearly = [
        validate_year(
            year,
            start,
            end,
            event_root,
            manifest_root,
            args.min_source_url_coverage,
        )
        for year in years
    ]
    failed_years = [int(r["year"]) for r in yearly if not r["pass"]]
    add_failure(failures, bool(failed_years), f"yearly completion/canonicality failed: {failed_years}")

    report = {
        "gate_version": GATE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "upstream_validation": {
            "path": str(upstream_path),
            "schema_version": upstream.get("schema_version"),
            "pass": upstream_pass,
        },
        "canonical_archive_contract": {
            "authoritative_writer": "v4_17_point_in_time_announcement_backfill.py",
            "schema_version": CANONICAL_SCHEMA_VERSION,
            "source_provider": CANONICAL_SOURCE_PROVIDER,
            "source_endpoint": CANONICAL_SOURCE_ENDPOINT,
            "event_type": CANONICAL_EVENT_TYPE,
            "event_id": "full lowercase SHA-256(provider|published_date|stock_code_raw|title|source_url)",
            "multiple_writer_mutation_allowed": False,
        },
        "completion": {
            "expected_years": years,
            "passed_years": [int(r["year"]) for r in yearly if r["pass"]],
            "failed_years": failed_years,
            "expected_calendar_days": sum(int(r["expected_calendar_days"]) for r in yearly),
            "terminal_request_days": sum(int(r["terminal_request_days"]) for r in yearly),
            "event_rows": sum(int(r["event_rows"]) for r in yearly),
            "years": yearly,
        },
        "pit_contract": {
            "raw_timestamp_precision": "date",
            "raw_available_at_is_fabricated": False,
            "same_day_intraday_use_allowed": False,
            "raw_causal_use_policy": CANONICAL_CAUSAL_POLICY,
            "downstream_materialization_rule": (
                "available_trade_date must equal the strictly next A-share trading session "
                "after published_date, derived from the frozen historical market calendar"
            ),
            "retrieved_at_semantics": "ingestion time only; never historical first_seen_at",
        },
        "theme_mapping_contract": {
            "raw_archive_contains_theme_mapping": False,
            "current_concept_membership_backfill_allowed": False,
            "future_theme_mapping_requirement": (
                "derived mappings must live outside the raw source archive and carry "
                "mapping_known_at provenance before causal research use"
            ),
        },
        "research_eligibility": {
            "h04_h05_allowed": not failures,
            "next_stage_if_pass": "V4.18 causal event view + preregistered event clustering",
            "blocked_if_fail": "Do not run/promote H04/H05 while this gate fails",
        },
        "validation": {"pass": not failures, "failures": failures},
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if failures:
        raise SystemExit("V4.17 full-backfill gate failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
