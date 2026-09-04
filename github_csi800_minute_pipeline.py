"""Resumable GitHub-friendly CSI800 BaoStock 5-minute backfill.

The research universe is the historical HS300+ZZ500 membership at ``asof``,
then filtered using information available on that date to match this project's
policy: main board + ChiNext only, excluding STAR, ST, N-labelled new listings,
and securities with fewer than 120 trading days since IPO.

Only missing symbols are downloaded through ``baostock_minute_backfill``. A
small JSON state is persisted so later GitHub Actions runs do not need to pull
every previously committed Git-LFS parquet merely to know what is complete.
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
UNIVERSE_POLICY = "mainboard_chinext_no_star_no_st_no_n_listing_ge120_v1"


def _rows(result: Any, label: str) -> list[dict[str, str]]:
    if str(result.error_code) != "0":
        raise RuntimeError(f"{label} failed: {result.error_code} {result.error_msg}")
    rows: list[dict[str, str]] = []
    while result.next():
        rows.append(dict(zip(result.fields, result.get_row_data())))
    return rows


def _query_constituents(query: Callable[..., Any], asof: pd.Timestamp) -> list[dict[str, str]]:
    return _rows(query(date=asof.strftime("%Y-%m-%d")), "constituent query")


def _allowed_board(code: str) -> bool:
    # Shanghai main board and Shenzhen main board + ChiNext. CSI800 does not
    # normally contain B shares, but explicit prefixes make the policy auditable.
    return code.startswith(("600", "601", "603", "605", "000", "001", "002", "003", "300", "301"))


def _historical_universe_metadata(asof: pd.Timestamp) -> tuple[dict[str, str], dict[str, pd.Timestamp], pd.DatetimeIndex]:
    all_stock = _rows(bs.query_all_stock(day=asof.strftime("%Y-%m-%d")), "query_all_stock")
    historical_names = {
        normalize_code(row.get("code")) or "": str(row.get("code_name", "")).strip()
        for row in all_stock
        if normalize_code(row.get("code"))
    }

    basics = _rows(bs.query_stock_basic(), "query_stock_basic")
    ipo_dates: dict[str, pd.Timestamp] = {}
    for row in basics:
        code = normalize_code(row.get("code"))
        ipo = pd.to_datetime(row.get("ipoDate", row.get("ipo_date", "")), errors="coerce")
        if code and not pd.isna(ipo):
            ipo_dates[code] = pd.Timestamp(ipo).normalize()

    trade_rows = _rows(
        bs.query_trade_dates(start_date="1990-01-01", end_date=asof.strftime("%Y-%m-%d")),
        "query_trade_dates",
    )
    trade_dates = pd.DatetimeIndex(
        sorted(
            pd.Timestamp(value).normalize()
            for row in trade_rows
            if str(row.get("is_trading_day", row.get("isTradingDay", "0"))) == "1"
            for value in [pd.to_datetime(row.get("calendar_date", row.get("calendarDate", "")), errors="coerce")]
            if not pd.isna(value)
        )
    )
    if trade_dates.empty:
        raise ValueError("BaoStock returned no trading calendar")
    return historical_names, ipo_dates, trade_dates


def _listing_trading_days(ipo: pd.Timestamp | None, asof: pd.Timestamp, trade_dates: pd.DatetimeIndex) -> int | None:
    if ipo is None or pd.isna(ipo):
        return None
    left = int(trade_dates.searchsorted(pd.Timestamp(ipo).normalize(), side="left"))
    right = int(trade_dates.searchsorted(asof.normalize(), side="right"))
    return max(0, right - left)


def freeze_csi800(asof: pd.Timestamp) -> tuple[list[str], dict[str, Any]]:
    login = bs.login()
    if str(login.error_code) != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    try:
        hs300 = _query_constituents(bs.query_hs300_stocks, asof)
        zz500 = _query_constituents(bs.query_zz500_stocks, asof)
        historical_names, ipo_dates, trade_dates = _historical_universe_metadata(asof)
    finally:
        bs.logout()

    raw_by_code: dict[str, dict[str, str]] = {}
    for family, rows in (("hs300", hs300), ("zz500", zz500)):
        for row in rows:
            code = normalize_code(row.get("code"))
            if not code:
                continue
            instrument = instrument_from_code(code)
            if instrument is None or not instrument.startswith(("SH", "SZ")):
                continue
            raw_by_code[code] = {
                "code": code,
                "instrument": instrument,
                "family": family,
                "update_date": str(row.get("updateDate", row.get("update_date", ""))),
            }

    if not 760 <= len(raw_by_code) <= 820:
        raise ValueError(
            f"Unexpected raw CSI800 size {len(raw_by_code)} at {asof.date()}; "
            "expected roughly 800 HS300+ZZ500 constituents"
        )

    included: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []
    for code, row in sorted(raw_by_code.items()):
        name = historical_names.get(code, "")
        name_upper = name.upper().strip()
        ipo = ipo_dates.get(code)
        listing_days = _listing_trading_days(ipo, asof, trade_dates)
        reasons: list[str] = []
        if not _allowed_board(code):
            reasons.append("outside_mainboard_chinext")
        if code.startswith(("688", "689")):
            reasons.append("star_market")
        if name_upper.startswith("ST") or name_upper.startswith("*ST"):
            reasons.append("st_asof")
        if name_upper.startswith("N"):
            reasons.append("n_label_asof")
        if listing_days is None or listing_days < 120:
            reasons.append("listing_lt_120_trading_days")

        record = {
            **row,
            "name_asof": name,
            "ipo_date": None if ipo is None else str(ipo.date()),
            "listing_trading_days_asof": listing_days,
        }
        if reasons:
            excluded.append({**record, "reasons": reasons})
        else:
            included[code] = record

    codes = sorted(included)
    if not 600 <= len(codes) <= 800:
        raise ValueError(
            f"Unexpected filtered universe size {len(codes)} at {asof.date()}; "
            "main-board + ChiNext CSI800 subset should remain broad"
        )

    UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"csi800_{asof.strftime('%Y%m%d')}"
    (UNIVERSE_DIR / f"{stem}.txt").write_text("\n".join(codes) + "\n", encoding="utf-8")
    payload = {
        "asof": asof.strftime("%Y-%m-%d"),
        "source": "BaoStock historical HS300 + ZZ500, query_all_stock, stock_basic, trade_dates",
        "policy": UNIVERSE_POLICY,
        "raw_csi800_count": len(raw_by_code),
        "count": len(codes),
        "excluded_count": len(excluded),
        "constituents": [included[code] for code in codes],
        "excluded": excluded,
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
    old: dict[str, Any] = {}
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            old = {}
        if old.get("config") == config:
            return old
        old_config = old.get("config", {})
        same_window = all(old_config.get(key) == config.get(key) for key in ("asof", "start", "end"))
        if same_window:
            # A stricter universe-policy revision does not invalidate prices
            # already downloaded for symbols that remain eligible.
            return {
                "config": config,
                "completed": list(old.get("completed", [])),
                "attempts": dict(old.get("attempts", {})),
                "runs": list(old.get("runs", [])),
                "created_utc": old.get("created_utc", datetime.now(timezone.utc).isoformat()),
                "migrated_from_config": old_config,
            }
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
        "universe_policy": UNIVERSE_POLICY,
    }
    state = _load_state(state_path, config)
    completed = set(map(str, state.get("completed", []))) & set(instruments)
    attempts = state.setdefault("attempts", {})

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
    # Repeated provider failures rotate behind never-attempted instruments so a
    # delisted/provider-edge symbol cannot block the whole CSI800 backfill.
    missing.sort(key=lambda item: (int(attempts.get(item, 0)), item))
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
    state["raw_csi800_count"] = universe["raw_csi800_count"]
    state["remaining_preview"] = remaining[:50]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_path = PROJECT_ROOT / "output" / "github_csi800_minute_status.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "state_file": str(state_path.relative_to(PROJECT_ROOT)),
        "universe_file": f"data_lake/universe/csi800_{asof.strftime('%Y%m%d')}.txt",
        "universe_policy": UNIVERSE_POLICY,
        "raw_csi800_count": universe["raw_csi800_count"],
        "filtered_universe_count": universe["count"],
        "excluded_count": universe["excluded_count"],
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
