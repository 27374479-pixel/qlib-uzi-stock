"""Point-in-time daily A-share name/trading-status snapshots for a frozen universe.

The minute endpoint does not carry historical ST/name flags. BaoStock's
``query_all_stock(day=...)`` does, so this collector records only the selected
universe on each historical trading day. Long anonymous BaoStock sessions can
drop, therefore the collector reconnects periodically and retries each day.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import baostock as bs
import pandas as pd

from config import PROJECT_ROOT
from eastmoney_recent_backfill import instrument_from_code, normalize_code

STATUS_DIR = PROJECT_ROOT / "data_lake" / "raw" / "baostock" / "daily_status"


def _rows(result, label: str) -> list[dict[str, str]]:
    if str(result.error_code) != "0":
        raise RuntimeError(f"{label} failed: {result.error_code} {result.error_msg}")
    rows: list[dict[str, str]] = []
    while result.next():
        rows.append(dict(zip(result.fields, result.get_row_data())))
    return rows


def _login() -> None:
    login = bs.login()
    if str(login.error_code) != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")


def _reconnect() -> None:
    try:
        bs.logout()
    except Exception:
        pass
    _login()


def _all_stock_for_day(day: str, retries: int = 4) -> list[dict[str, str]]:
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return _rows(bs.query_all_stock(day=day), f"query_all_stock({day})")
        except Exception as exc:
            error = exc
            if attempt < retries:
                time.sleep(min(5.0, float(attempt)))
                _reconnect()
    raise RuntimeError(f"query_all_stock({day}) exhausted retries: {error}")


def load_universe(path: Path) -> set[str]:
    return {
        code
        for code in (normalize_code(item) for item in path.read_text(encoding="utf-8").splitlines())
        if code
    }


def collect(universe_file: Path, start: pd.Timestamp, end: pd.Timestamp, output: Path) -> pd.DataFrame:
    codes = load_universe(universe_file)
    if not codes:
        raise ValueError(f"empty universe: {universe_file}")
    _login()
    try:
        calendar = _rows(
            bs.query_trade_dates(start_date=start.strftime("%Y-%m-%d"), end_date=end.strftime("%Y-%m-%d")),
            "query_trade_dates",
        )
        dates = [
            str(row.get("calendar_date", row.get("calendarDate", "")))
            for row in calendar
            if str(row.get("is_trading_day", row.get("isTradingDay", "0"))) == "1"
        ]
        frames: list[pd.DataFrame] = []
        for number, day in enumerate(dates, 1):
            # BaoStock has historically dropped long anonymous sessions after
            # dozens of requests. Re-login before that becomes a correctness
            # issue, and still retry individual days for transient failures.
            if number > 1 and (number - 1) % 40 == 0:
                _reconnect()
            rows = _all_stock_for_day(day)
            selected: list[dict[str, object]] = []
            for row in rows:
                code = normalize_code(row.get("code"))
                if code not in codes:
                    continue
                name = str(row.get("code_name", "")).strip()
                upper = name.upper()
                instrument = instrument_from_code(code)
                if not instrument:
                    continue
                selected.append(
                    {
                        "date": day,
                        "instrument": instrument,
                        "code": code,
                        "name_asof": name,
                        "trade_status": pd.to_numeric(row.get("tradeStatus", row.get("trade_status", "")), errors="coerce"),
                        "is_st": bool(upper.startswith("ST") or upper.startswith("*ST")),
                        "is_n": bool(upper.startswith("N")),
                    }
                )
            if selected:
                frames.append(pd.DataFrame(selected))
            if number == 1 or number % 25 == 0 or number == len(dates):
                print(f"daily status {number}/{len(dates)} {day} rows={len(selected)}", flush=True)
    finally:
        try:
            bs.logout()
        except Exception:
            pass

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if result.empty:
        raise ValueError("no daily status rows collected")
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
    result["downloaded_at"] = datetime.now(timezone.utc).isoformat()
    result = result.dropna(subset=["date", "instrument"]).drop_duplicates(["date", "instrument"], keep="last")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    result.to_parquet(temp, index=False, compression="zstd")
    temp.replace(output)
    print(
        f"status result={output} dates={result['date'].nunique()} instruments={result['instrument'].nunique()} rows={len(result)}",
        flush=True,
    )
    return result


def _date(value: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(value)
    return pd.Timestamp(parsed).normalize()


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect point-in-time daily status for a frozen universe")
    parser.add_argument("--universe-file", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    start = _date(args.start)
    end = _date(args.end)
    output = args.output or STATUS_DIR / f"{args.universe_file.stem}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.parquet"
    collect(args.universe_file, start, end, output)


if __name__ == "__main__":
    main()
