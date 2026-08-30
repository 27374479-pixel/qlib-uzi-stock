"""Direct Eastmoney recent-data backfill for the five short-term research styles.

The project already had a small Sina/AKShare minute cache.  This module talks to
Eastmoney's public JSON endpoints directly so that the recent 5-minute window
and limit-up/limit-down/broken-board snapshots can be refreshed without using
AKShare as the transport layer.

Important research conventions:

* minute prices are unadjusted (``fqt=0``); corporate-action adjusted prices
  are not executable prices;
* each minute row's ``knowledge_time`` is the bar timestamp, so a replay can
  only use rows at or before its signal timestamp;
* event-pool files are treated as end-of-day audit data.  The backtest must
  reconstruct intraday board state from minute bars and must not use a final
  pool's ``last seal`` or ``break count`` as an intraday signal.

Examples
--------
    .venv\\Scripts\\python.exe eastmoney_recent_backfill.py \
        --start 20260624 --end 20260824 --universe csi800 --workers 8

    # Smoke test before a broad download
    .venv\\Scripts\\python.exe eastmoney_recent_backfill.py \
        --start 20260701 --end 20260824 --universe csi800 --max-codes 20
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import requests

from config import PROJECT_ROOT


MINUTE_DIR = PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "equity_5min"
RECENT_EVENT_DIR = PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "recent_events"
MANIFEST_DIR = PROJECT_ROOT / "data_lake" / "manifests"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)
MINUTE_HOSTS = (
    "92.push2his.eastmoney.com",
    "push2his.eastmoney.com",
    "82.push2his.eastmoney.com",
)
EVENT_HOSTS = ("push2ex.eastmoney.com", "82.push2ex.eastmoney.com")
MINUTE_UT = "fa5fd1943c7b386f172d6893dbfba10b"
EVENT_UT = "7eea3edcaed734bea9cbfc24409ed989"

MINUTE_COLUMNS = [
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
]

EVENT_ENDPOINTS = {
    "limit_up": ("getTopicZTPool", "10000", "fbt:asc"),
    "previous_limit_up": ("getYesterdayZTPool", "5000", "zs:desc"),
    "limit_down": ("getTopicDTPool", "10000", "fund:asc"),
    "broken_board": ("getTopicZBPool", "5000", "fbt:asc"),
}


@dataclass(frozen=True)
class BackfillConfig:
    start: str
    end: str
    universe: str = "csi800"
    workers: int = 8
    max_codes: int = 0
    skip_events: bool = False
    refresh: bool = False
    request_timeout: int = 20


def _session() -> requests.Session:
    session = requests.Session()
    # The configured desktop proxy intermittently resets Eastmoney's direct
    # endpoints.  Keep this request path explicitly direct.
    session.trust_env = False
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "application/json,text/plain,*/*",
        }
    )
    return session


def _safe_json(response: requests.Response) -> dict[str, Any]:
    # Eastmoney's event endpoint has returned GB18030 payloads while the HTTP
    # header says UTF-8.  Prefer the decoding with fewer replacement
    # characters; otherwise Chinese names and ``hybk`` themes become unusable.
    candidates: list[tuple[int, str]] = []
    for encoding in ("utf-8", "gb18030"):
        text = response.content.decode(encoding, errors="replace")
        candidates.append((text.count("\ufffd"), text))
    for _, text in sorted(candidates, key=lambda item: item[0]):
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                return value
        except Exception:
            # A few Eastmoney hosts occasionally return JSONP despite no
            # callback.  Try the same extraction below.
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    value = json.loads(text[start:end])
                    if isinstance(value, dict):
                        return value
                except Exception:
                    continue
    raise ValueError(f"Eastmoney response is not JSON: {text[:160]}")


def _get_json(
    hosts: Iterable[str],
    path: str,
    params: dict[str, Any],
    timeout: int,
    retries: int = 2,
) -> dict[str, Any]:
    errors: list[str] = []
    for attempt in range(retries):
        for host in hosts:
            session = _session()
            try:
                response = session.get(
                    f"https://{host}{path}",
                    params=params,
                    timeout=timeout,
                )
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                payload = _safe_json(response)
                if payload.get("rc", 0) not in (0, None):
                    raise RuntimeError(f"rc={payload.get('rc')}")
                return payload
            except Exception as exc:  # pragma: no cover - network dependent
                errors.append(f"{host}: {type(exc).__name__}: {exc}")
            finally:
                session.close()
        # Keep a failed code cheap.  The caller can rerun a bounded batch and
        # resume from disk; a per-code multi-minute retry would stall thousands
        # of otherwise independent requests when Eastmoney rate-limits a host.
        time.sleep(min(2.0, 0.35 * (attempt + 1)) + random.random() * 0.15)
    raise RuntimeError("; ".join(errors[-8:]))


def normalize_code(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip().upper()
    text = text.replace("SH", "").replace("SZ", "").replace("BJ", "")
    digits = re.sub(r"[^0-9]", "", text)
    if not digits:
        return None
    return digits.zfill(6)


def instrument_from_code(value: Any) -> str | None:
    code = normalize_code(value)
    if code is None:
        return None
    if code.startswith("6"):
        return f"SH{code}"
    if code.startswith(("4", "8", "9")):
        return f"BJ{code}"
    return f"SZ{code}"


def secid_from_instrument(instrument: str) -> str:
    code = normalize_code(instrument) or ""
    # CSI800 does not normally include BSE names; Eastmoney uses market 0 for
    # the Shenzhen/BSE-style securities in this endpoint.
    return f"1.{code}" if code.startswith("6") else f"0.{code}"


def _parse_date(value: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid date: {value}")
    return parsed.normalize()


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def _normalise_minute_rows(
    rows: list[str], instrument: str, downloaded_at: str
) -> pd.DataFrame:
    parsed: list[list[str]] = []
    for line in rows:
        values = str(line).split(",")
        if len(values) >= len(MINUTE_COLUMNS):
            parsed.append(values[: len(MINUTE_COLUMNS)])
    if not parsed:
        return pd.DataFrame()
    frame = pd.DataFrame(parsed, columns=MINUTE_COLUMNS)
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
    for column in MINUTE_COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame.insert(0, "instrument", instrument)
    frame["source"] = "eastmoney_push2his_5min"
    frame["knowledge_time"] = frame["datetime"]
    frame["downloaded_at"] = downloaded_at
    return (
        frame.dropna(subset=["datetime", "open", "close"])
        .drop_duplicates(["instrument", "datetime"], keep="last")
        .sort_values("datetime")
        .reset_index(drop=True)
    )


def fetch_minute_history(
    instrument: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    timeout: int,
    refresh: bool = False,
) -> tuple[str, int, str | None, str | None, str | None]:
    """Fetch and merge one instrument; return a compact manifest row."""

    path = MINUTE_DIR / f"{instrument}.parquet"
    cached = pd.DataFrame()
    if path.exists() and not refresh:
        try:
            cached = pd.read_parquet(path)
            if "datetime" in cached:
                cached["datetime"] = pd.to_datetime(cached["datetime"], errors="coerce")
                max_date = cached["datetime"].max()
                if pd.notna(max_date) and max_date.normalize() >= end:
                    actual = cached.loc[cached["datetime"].between(start, end)]
                    return instrument, int(len(actual)), None, str(actual["datetime"].min()), str(actual["datetime"].max())
        except Exception:
            cached = pd.DataFrame()

    params = {
        "secid": secid_from_instrument(instrument),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "5",
        "fqt": "0",
        "beg": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "lmt": "100000",
        "ut": MINUTE_UT,
    }
    try:
        payload = _get_json(
            MINUTE_HOSTS,
            "/api/qt/stock/kline/get",
            params,
            timeout=timeout,
        )
        data = payload.get("data") or {}
        fresh = _normalise_minute_rows(
            data.get("klines") or [],
            instrument,
            datetime.now().isoformat(timespec="seconds"),
        )
        if fresh.empty:
            raise ValueError("no minute rows returned")
        combined = pd.concat([cached, fresh], ignore_index=True) if not cached.empty else fresh
        combined["datetime"] = pd.to_datetime(combined["datetime"], errors="coerce")
        combined = (
            combined.dropna(subset=["datetime"])
            .drop_duplicates(["instrument", "datetime"], keep="last")
            .sort_values(["instrument", "datetime"])
            .reset_index(drop=True)
        )
        _atomic_parquet(combined, path)
        selected = combined.loc[combined["datetime"].between(start, end)]
        return instrument, int(len(selected)), None, str(selected["datetime"].min()), str(selected["datetime"].max())
    except Exception as exc:
        return instrument, 0, f"{type(exc).__name__}: {exc}", None, None


def _scalar(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _normalise_event_pool(
    pool: list[dict[str, Any]], event_type: str, pool_date: str, downloaded_at: str
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in pool:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {
            "pool_date": pool_date,
            "event_type": event_type,
            "code": normalize_code(item.get("c")),
            "instrument": instrument_from_code(item.get("c")),
            "market": item.get("m"),
            "name": item.get("n"),
            "source": "eastmoney_push2ex",
            "knowledge_time": downloaded_at,
            "raw_json": json.dumps(item, ensure_ascii=False, separators=(",", ":")),
        }
        # Keep common numeric/time fields in a stable schema.  The complete
        # vendor payload remains in raw_json because endpoints differ slightly.
        for key in (
            "p", "ztp", "zdp", "amount", "ltsz", "tshare", "hs", "fund",
            "fbt", "lbt", "zbc", "zttj", "hybk", "days", "ct", "ztf", "jzf",
            "lbc", "zdp", "ztime", "jtime",
        ):
            if key in item:
                value = item[key]
                if isinstance(value, dict):
                    row[f"em_{key}"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    if key == "zttj":
                        row["board_days"] = value.get("days")
                        row["board_count"] = value.get("ct")
                else:
                    row[f"em_{key}"] = _scalar(value)
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["pool_date", "code"]).reset_index(drop=True)


def fetch_event_snapshot(
    event_type: str,
    pool_date: pd.Timestamp,
    timeout: int,
) -> tuple[str, str, int, str | None]:
    endpoint, pagesize, sort = EVENT_ENDPOINTS[event_type]
    params = {
        "ut": EVENT_UT,
        "dpt": "wz.ztzt",
        "Pageindex": "0",
        "pagesize": pagesize,
        "sort": sort,
        "date": pool_date.strftime("%Y%m%d"),
    }
    try:
        payload = _get_json(EVENT_HOSTS, f"/{endpoint}", params, timeout=timeout)
        data = payload.get("data") or {}
        frame = _normalise_event_pool(
            data.get("pool") or [],
            event_type,
            pool_date.strftime("%Y%m%d"),
            datetime.now().isoformat(timespec="seconds"),
        )
        if frame.empty:
            # Do not overwrite a previously downloaded non-empty file with the
            # API's empty response for an unavailable historical date.
            return event_type, pool_date.strftime("%Y%m%d"), 0, None
        path = RECENT_EVENT_DIR / event_type / f"{pool_date:%Y%m%d}.parquet"
        _atomic_parquet(frame, path)
        return event_type, pool_date.strftime("%Y%m%d"), int(len(frame)), None
    except Exception as exc:
        return event_type, pool_date.strftime("%Y%m%d"), 0, f"{type(exc).__name__}: {exc}"


def _codes_from_frame(path: Path) -> set[str]:
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return set()
    candidates: list[tuple[int, pd.Series]] = []
    for column in frame.columns:
        values = frame[column].astype(str).str.extract(r"(\d{6})", expand=False)
        score = int(values.notna().sum())
        if score:
            candidates.append((score, values))
    if not candidates:
        return set()
    _, values = max(candidates, key=lambda item: item[0])
    return {item for item in values.dropna().map(normalize_code) if item}


def local_event_codes() -> set[str]:
    codes: set[str] = set()
    current_root = PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "current"
    current_names = {
        "limit_up": "limit_up_pool",
        "previous_limit_up": "previous_limit_up_pool",
        "limit_down": "limit_down_pool",
        "broken_board": "broken_board_pool",
    }
    roots = [current_root / current_names[name] for name in EVENT_ENDPOINTS] + [RECENT_EVENT_DIR]
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("**/*.parquet"):
            codes.update(_codes_from_frame(path))
    return codes


def load_universe(name: str, codes_file: str | None = None) -> set[str]:
    if codes_file:
        values = Path(codes_file).read_text(encoding="utf-8").splitlines()
        return {code for code in (normalize_code(item) for item in values) if code}
    if name == "existing":
        return {
            code
            for code in (
                normalize_code(path.stem)
                for path in MINUTE_DIR.glob("*.parquet")
            )
            if code
        }
    if name != "csi800":
        raise ValueError(f"unsupported universe: {name}")
    import qlib
    from qlib.constant import REG_CN
    from qlib.data import D
    from config import QLIB_DATA_DIR

    qlib.init(provider_uri=str(QLIB_DATA_DIR), region=REG_CN)
    market = D.instruments(market="csi800")
    instruments = D.list_instruments(instruments=market, as_list=True)
    return {
        code
        for code in (
            normalize_code(item)
            for item in instruments
        )
        if code
    }


def _trading_like_dates(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    # The event endpoints return an empty pool for weekends and holidays.  A
    # weekday loop is enough here and avoids adding another vendor dependency.
    return [item.normalize() for item in pd.date_range(start, end, freq="B")]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def parse_args() -> argparse.Namespace:
    today = datetime.now().strftime("%Y%m%d")
    start = (pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=62)).strftime("%Y%m%d")
    parser = argparse.ArgumentParser(description="Backfill recent Eastmoney 5-minute and event data")
    parser.add_argument("--start", default=start, help="YYYYMMDD")
    parser.add_argument("--end", default=today, help="YYYYMMDD")
    parser.add_argument("--universe", choices=["csi800", "existing"], default="csi800")
    parser.add_argument("--codes-file", default=None)
    parser.add_argument("--workers", type=int, default=BackfillConfig.workers)
    parser.add_argument("--max-codes", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0, help="start offset after sorting the code universe")
    parser.add_argument("--skip-events", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--timeout", type=int, default=BackfillConfig.request_timeout)
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    start = _parse_date(args.start)
    end = _parse_date(args.end)
    if end < start:
        raise ValueError("end must be on or after start")
    config = BackfillConfig(
        start=start.strftime("%Y%m%d"),
        end=end.strftime("%Y%m%d"),
        universe=args.universe,
        workers=max(1, args.workers),
        max_codes=max(0, args.max_codes),
        skip_events=bool(args.skip_events),
        refresh=bool(args.refresh),
        request_timeout=max(5, args.timeout),
    )

    event_rows: list[dict[str, Any]] = []
    if not config.skip_events:
        dates = _trading_like_dates(start, end)
        jobs = [(event_type, date) for event_type in EVENT_ENDPOINTS for date in dates]
        print(f"Eastmoney events: {len(jobs)} requests", flush=True)
        with ThreadPoolExecutor(max_workers=min(4, config.workers)) as executor:
            futures = {
                executor.submit(fetch_event_snapshot, event_type, date, config.request_timeout): (event_type, date)
                for event_type, date in jobs
            }
            for number, future in enumerate(as_completed(futures), 1):
                event_type, date, rows, error = future.result()
                event_rows.append(
                    {"event_type": event_type, "date": date, "rows": rows, "error": error}
                )
                if number == 1 or number % 40 == 0 or number == len(futures):
                    ok = sum(item["rows"] > 0 for item in event_rows)
                    print(f"  events {number}/{len(futures)} nonempty={ok}", flush=True)

    codes = load_universe(args.universe, args.codes_file)
    codes.update(local_event_codes())
    sorted_codes = sorted(codes)
    offset = max(0, int(args.offset))
    if config.max_codes:
        sorted_codes = sorted_codes[offset : offset + config.max_codes]
    elif offset:
        sorted_codes = sorted_codes[offset:]
    codes = set(sorted_codes)
    instruments = sorted(
        instrument
        for instrument in (instrument_from_code(code) for code in codes)
        if instrument
    )
    print(f"Minute universe: {len(instruments)} instruments", flush=True)

    minute_rows: list[dict[str, Any]] = []
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=config.workers) as executor:
        futures = {
            executor.submit(
                fetch_minute_history,
                instrument,
                start,
                end,
                config.request_timeout,
                config.refresh,
            ): instrument
            for instrument in instruments
        }
        for number, future in enumerate(as_completed(futures), 1):
            instrument, rows, error, actual_start, actual_end = future.result()
            item = {
                "instrument": instrument,
                "rows": rows,
                "actual_start": actual_start,
                "actual_end": actual_end,
                "error": error,
            }
            minute_rows.append(item)
            if error:
                failures[instrument] = error
            if number == 1 or number % 100 == 0 or number == len(futures):
                print(
                    f"  minute {number}/{len(futures)} "
                    f"ok={sum(item['rows'] > 0 for item in minute_rows)} "
                    f"failed={len(failures)}",
                    flush=True,
                )

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": asdict(config),
        "minute": {
            "requested_instruments": len(instruments),
            "success": sum(item["rows"] > 0 for item in minute_rows),
            "failures": failures,
            "rows": sum(item["rows"] for item in minute_rows),
            "actual_start": min((item["actual_start"] for item in minute_rows if item["actual_start"]), default=None),
            "actual_end": max((item["actual_end"] for item in minute_rows if item["actual_end"]), default=None),
        },
        "events": {
            "requests": len(event_rows),
            "nonempty": sum(item["rows"] > 0 for item in event_rows),
            "rows": sum(item["rows"] for item in event_rows),
            "failures": [item for item in event_rows if item["error"]],
        },
        "notes": [
            "Minute prices use Eastmoney push2his, unadjusted fqt=0.",
            "Eastmoney may cap the available intraday history; actual coverage is reported above.",
            "Event-pool rows are end-of-day audit data and are not used as intraday signals.",
        ],
    }
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = MANIFEST_DIR / f"eastmoney_recent_backfill_{stamp}.json"
    path.write_text(json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2))
    print(f"manifest: {path}")
    return manifest


if __name__ == "__main__":
    main()
