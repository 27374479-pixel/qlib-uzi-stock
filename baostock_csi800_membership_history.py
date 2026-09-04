"""Build a no-future CSI800 membership history directly from BaoStock.

For first-stage book-alpha research we do not need to know a future index
rebalance before it is observable.  At each snapshot date we query HS300 and
ZZ500 with that historical date and carry that snapshot forward only until the
next snapshot.  ``weekly`` is the default compromise for broad screening;
final validation can rerun with ``daily`` cadence.

The output TSV uses Qlib's ``instrument<TAB>start<TAB>end`` interval format and
can therefore be copied into ``qlib_data/cn_data/instruments/csi800.txt``.
Raw snapshot membership is also stored as parquet for audit/reconstruction.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import baostock as bs
import pandas as pd

from config import PROJECT_ROOT

UNIVERSE_DIR = PROJECT_ROOT / "data_lake" / "universe"


def _rows(result: Any, label: str) -> list[dict[str, str]]:
    if str(result.error_code) != "0":
        raise RuntimeError(f"{label} failed: {result.error_code} {result.error_msg}")
    rows: list[dict[str, str]] = []
    while result.next():
        rows.append(dict(zip(result.fields, result.get_row_data())))
    return rows


def _login() -> None:
    result = bs.login()
    if str(result.error_code) != "0":
        raise RuntimeError(f"BaoStock login failed: {result.error_code} {result.error_msg}")


def _reconnect() -> None:
    try:
        bs.logout()
    except Exception:
        pass
    _login()


def normalize(code: str | None) -> str | None:
    value = str(code or "").lower().strip()
    if value.startswith("sh.") and len(value) == 9:
        return "SH" + value[3:]
    if value.startswith("sz.") and len(value) == 9:
        return "SZ" + value[3:]
    return None


def allowed_board(instrument: str) -> bool:
    return instrument.startswith((
        "SH600", "SH601", "SH603", "SH605",
        "SZ000", "SZ001", "SZ002", "SZ003", "SZ300", "SZ301",
    ))


def trading_dates(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    rows = _rows(
        bs.query_trade_dates(start_date=str(start.date()), end_date=str(end.date())),
        "query_trade_dates",
    )
    values = [
        pd.Timestamp(row.get("calendar_date", row.get("calendarDate"))).normalize()
        for row in rows
        if str(row.get("is_trading_day", row.get("isTradingDay", "0"))) == "1"
    ]
    return pd.DatetimeIndex(sorted(set(values)))


def snapshot_dates(cal: pd.DatetimeIndex, cadence: str) -> list[pd.Timestamp]:
    if cadence == "daily":
        return [pd.Timestamp(x) for x in cal]
    frame = pd.DataFrame({"date": cal})
    if cadence == "weekly":
        frame["bucket"] = frame["date"].dt.to_period("W-FRI").astype(str)
    elif cadence == "monthly":
        frame["bucket"] = frame["date"].dt.to_period("M").astype(str)
    else:
        raise ValueError(f"unsupported cadence {cadence}")
    return [pd.Timestamp(x) for x in frame.groupby("bucket", sort=True)["date"].min()]


def _query_family(query: Callable[..., Any], date: pd.Timestamp, label: str, retries: int) -> list[dict[str, str]]:
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return _rows(query(date=str(date.date())), f"{label}({date.date()})")
        except Exception as exc:
            error = exc
            if attempt < retries:
                time.sleep(float(attempt))
                _reconnect()
    raise RuntimeError(f"{label}({date.date()}) exhausted retries: {error}")


def collect_snapshots(dates: list[pd.Timestamp], retries: int = 4) -> pd.DataFrame:
    records: list[dict[str, str]] = []
    _login()
    try:
        for number, date in enumerate(dates, 1):
            if number > 1 and (number - 1) % 40 == 0:
                _reconnect()
            families = (
                ("hs300", _query_family(bs.query_hs300_stocks, date, "hs300", retries)),
                ("zz500", _query_family(bs.query_zz500_stocks, date, "zz500", retries)),
            )
            raw_codes: set[str] = set()
            for family, rows in families:
                for row in rows:
                    instrument = normalize(row.get("code"))
                    if not instrument:
                        continue
                    raw_codes.add(instrument)
                    if not allowed_board(instrument):
                        continue
                    records.append(
                        {
                            "snapshot_date": str(date.date()),
                            "instrument": instrument,
                            "family": family,
                            "provider_update_date": str(row.get("updateDate", row.get("update_date", ""))),
                            "name": str(row.get("code_name", "")),
                        }
                    )
            if not 740 <= len(raw_codes) <= 820:
                raise ValueError(f"unexpected raw CSI800 count={len(raw_codes)} on {date.date()}")
            if number == 1 or number % 25 == 0 or number == len(dates):
                current = len({r['instrument'] for r in records if r['snapshot_date'] == str(date.date())})
                print(f"membership {number}/{len(dates)} {date.date()} allowed={current} raw={len(raw_codes)}", flush=True)
    finally:
        try:
            bs.logout()
        except Exception:
            pass
    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("no membership snapshots")
    frame["snapshot_date"] = pd.to_datetime(frame["snapshot_date"]).dt.normalize()
    return frame.drop_duplicates(["snapshot_date", "instrument"], keep="last").sort_values(["snapshot_date", "instrument"])


def compress_intervals(snapshots: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    dates = sorted(pd.to_datetime(snapshots["snapshot_date"]).dt.normalize().unique())
    members_by_date = {
        pd.Timestamp(date): set(snapshots.loc[snapshots["snapshot_date"].eq(pd.Timestamp(date)), "instrument"].astype(str))
        for date in dates
    }
    all_instruments = sorted(set().union(*members_by_date.values()))
    rows: list[dict[str, Any]] = []
    for instrument in all_instruments:
        active_start: pd.Timestamp | None = None
        for position, date_value in enumerate(dates):
            date = pd.Timestamp(date_value)
            present = instrument in members_by_date[date]
            if present and active_start is None:
                active_start = date
            next_date = pd.Timestamp(dates[position + 1]) if position + 1 < len(dates) else None
            if active_start is not None and (not present):
                # Membership was known absent at this snapshot, so the previous
                # interval ends the calendar day before this observation.
                rows.append({"instrument": instrument, "start": active_start, "end": date - pd.Timedelta(days=1)})
                active_start = None
            if active_start is not None and next_date is None:
                rows.append({"instrument": instrument, "start": active_start, "end": end})
        # The transition logic above closes on the first absent snapshot.  It
        # intentionally does not back-date a deletion to an unknown rebalance.
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("no intervals produced")
    result = result.loc[result["end"] >= result["start"]].sort_values(["instrument", "start"])
    return result


def write_outputs(snapshots: pd.DataFrame, intervals: pd.DataFrame, cadence: str, start: pd.Timestamp, end: pd.Timestamp, output: Path, snapshots_output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshots_output.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        f"{row.instrument}\t{pd.Timestamp(row.start):%Y-%m-%d}\t{pd.Timestamp(row.end):%Y-%m-%d}\n"
        for row in intervals.itertuples(index=False)
    )
    output.write_text(text, encoding="utf-8")
    snapshots.to_parquet(snapshots_output, index=False, compression="zstd")
    meta = {
        "source": "BaoStock historical HS300 + ZZ500",
        "point_in_time_policy": "snapshot membership is carried forward only until the next observed snapshot; changes are never back-dated",
        "cadence": cadence,
        "start": str(start.date()),
        "end": str(end.date()),
        "snapshot_dates": int(snapshots["snapshot_date"].nunique()),
        "unique_instruments": int(snapshots["instrument"].nunique()),
        "intervals": int(len(intervals)),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "final_validation_note": "weekly/monthly cadence is a conservative screening approximation; rerun daily cadence for final membership-sensitive claims",
    }
    output.with_suffix(output.suffix + ".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2), flush=True)
    return meta


def _date(value: str) -> pd.Timestamp:
    result = pd.to_datetime(value, errors="raise")
    return pd.Timestamp(result).normalize()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build point-in-time CSI800 membership history")
    parser.add_argument("--start", default="2014-01-01")
    parser.add_argument("--end", default="2026-09-03")
    parser.add_argument("--cadence", choices=["daily", "weekly", "monthly"], default="weekly")
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--output", type=Path, default=UNIVERSE_DIR / "csi800_membership_weekly.tsv")
    parser.add_argument("--snapshots-output", type=Path, default=UNIVERSE_DIR / "csi800_membership_weekly_snapshots.parquet")
    args = parser.parse_args()
    start, end = _date(args.start), _date(args.end)
    _login()
    try:
        cal = trading_dates(start, end)
    finally:
        try:
            bs.logout()
        except Exception:
            pass
    dates = snapshot_dates(cal, args.cadence)
    snapshots = collect_snapshots(dates, max(1, args.retries))
    intervals = compress_intervals(snapshots, end)
    write_outputs(snapshots, intervals, args.cadence, start, end, args.output, args.snapshots_output)


if __name__ == "__main__":
    main()
