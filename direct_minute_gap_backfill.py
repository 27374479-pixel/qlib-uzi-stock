"""Polite direct 5-minute gap filler for A-share validation.

Primary source: Eastmoney push2his HTTP API (no AKShare wrapper).
Fallback: Sina public minute API, used mainly as a best-effort recent-data source.

Designed for long, low-frequency collection runs rather than bursts:
- single-threaded only;
- fixed delay plus random jitter between symbols;
- exponential cooldown after failures;
- existing complete local files are skipped;
- each successful symbol is atomically persisted immediately;
- provider health circuit-breaker stops after repeated failures;
- no adjusted prices: execution backtests require actual traded prices.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
EM_DIR = ROOT / "data_lake" / "raw" / "eastmoney" / "equity_5min"
SINA_DIR = ROOT / "data_lake" / "raw" / "sina" / "equity_5min"
MANIFEST_DIR = ROOT / "data_lake" / "manifests"


def _secid(instrument: str) -> str:
    return ("1." if instrument.startswith("SH") else "0.") + instrument[2:]


def _normalize_existing(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        f = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()
    if "datetime" not in f.columns:
        return pd.DataFrame()
    f = f.copy()
    f["datetime"] = pd.to_datetime(f["datetime"], errors="coerce")
    return f.dropna(subset=["datetime"])


def _covers(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    if frame.empty or "datetime" not in frame.columns:
        return False
    lo = frame["datetime"].min()
    hi = frame["datetime"].max()
    return lo <= start + pd.Timedelta(days=7) and hi >= end - pd.Timedelta(days=7)


def _atomic_write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def fetch_eastmoney(session: requests.Session, instrument: str, start: pd.Timestamp, end: pd.Timestamp, timeout: float) -> pd.DataFrame:
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": _secid(instrument), "klt": "5", "fqt": "0",
        "beg": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
        "lmt": "1000000",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    klines = (payload.get("data") or {}).get("klines") or []
    if not klines:
        raise RuntimeError(f"eastmoney empty payload rc={payload.get('rc')}")
    rows = []
    for item in klines:
        p = str(item).split(",")
        if len(p) < 11:
            continue
        rows.append({
            "instrument": instrument, "datetime": p[0],
            "open": p[1], "close": p[2], "high": p[3], "low": p[4],
            "volume": p[5], "amount": p[6], "amplitude_pct": p[7],
            "return_pct": p[8], "change": p[9], "turnover_rate_pct": p[10],
            "source": "eastmoney_direct_5min",
        })
    f = pd.DataFrame(rows)
    if f.empty:
        raise RuntimeError("eastmoney returned no parseable bars")
    f["datetime"] = pd.to_datetime(f["datetime"], errors="coerce")
    for c in ["open", "close", "high", "low", "volume", "amount", "amplitude_pct", "return_pct", "change", "turnover_rate_pct"]:
        f[c] = pd.to_numeric(f[c], errors="coerce")
    f["knowledge_time"] = f["datetime"]
    return f.dropna(subset=["datetime", "open", "close"]).drop_duplicates(["instrument", "datetime"], keep="last").sort_values("datetime")


def fetch_sina(session: requests.Session, instrument: str, timeout: float) -> pd.DataFrame:
    url = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": instrument.lower(), "scale": "5", "ma": "no", "datalen": "1023"}
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("sina empty payload")
    f = pd.DataFrame(payload).rename(columns={"day": "datetime"})
    f.insert(0, "instrument", instrument)
    f["datetime"] = pd.to_datetime(f["datetime"], errors="coerce")
    for c in ["open", "high", "low", "close", "volume"]:
        if c in f:
            f[c] = pd.to_numeric(f[c], errors="coerce")
    f["source"] = "sina_direct_5min"
    f["knowledge_time"] = f["datetime"]
    return f.dropna(subset=["datetime", "open", "close"]).drop_duplicates(["instrument", "datetime"], keep="last").sort_values("datetime")


def merge_and_save(existing: pd.DataFrame, fresh: pd.DataFrame, path: Path) -> pd.DataFrame:
    merged = fresh.copy() if existing.empty else pd.concat([existing, fresh], ignore_index=True, sort=False)
    merged = merged.drop_duplicates(["instrument", "datetime"], keep="last").sort_values("datetime")
    _atomic_write(merged, path)
    return merged


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes-file", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--sleep", type=float, default=15.0, help="base delay between symbol requests")
    ap.add_argument("--jitter", type=float, default=8.0, help="uniform random extra delay [0,jitter]")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--max-symbols", type=int, default=1000000)
    ap.add_argument("--max-consecutive-failures", type=int, default=8)
    ap.add_argument("--failure-backoff", type=float, default=30.0, help="base exponential cooldown after failures")
    ap.add_argument("--max-backoff", type=float, default=300.0)
    args = ap.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end) + pd.Timedelta(hours=23, minutes=59)
    codes = [x.strip() for x in Path(args.codes_file).read_text(encoding="utf-8").splitlines() if x.strip()]
    EM_DIR.mkdir(parents=True, exist_ok=True); SINA_DIR.mkdir(parents=True, exist_ok=True); MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept": "application/json,text/plain,*/*", "Referer": "https://quote.eastmoney.com/", "Connection": "keep-alive",
    })

    results = []; consecutive = 0; attempted = 0
    for instrument in codes:
        em_path = EM_DIR / f"{instrument}.parquet"
        existing = _normalize_existing(em_path)
        if _covers(existing, start, end):
            results.append({"instrument": instrument, "status": "skip_complete", "source": "local", "bars": len(existing)})
            continue
        if attempted >= args.max_symbols:
            break
        attempted += 1
        status = None; error = None; merged = existing
        try:
            fresh = fetch_eastmoney(session, instrument, start, end, args.timeout)
            merged = merge_and_save(existing, fresh, em_path)
            status = "eastmoney_ok" if _covers(merged, start, end) else "eastmoney_partial"
            consecutive = 0
        except Exception as exc:
            error = f"eastmoney: {exc}"
            # Provider fallback is still one request at a time; no parallelism.
            try:
                time.sleep(random.uniform(2.0, 5.0))
                fresh = fetch_sina(session, instrument, args.timeout)
                sina_path = SINA_DIR / f"{instrument}.parquet"
                sina_existing = _normalize_existing(sina_path)
                sina_merged = merge_and_save(sina_existing, fresh, sina_path)
                status = "sina_ok" if _covers(sina_merged, start, end) else "sina_partial"
                consecutive = 0
            except Exception as exc2:
                error += f" | sina: {exc2}"
                status = "failed"
                consecutive += 1

        lo = str(merged["datetime"].min()) if not merged.empty and "datetime" in merged else None
        hi = str(merged["datetime"].max()) if not merged.empty and "datetime" in merged else None
        results.append({"instrument": instrument, "status": status, "bars": len(merged), "min_datetime": lo, "max_datetime": hi, "error": error})
        print(f"[{attempted}/{args.max_symbols}] {instrument} {status} bars={len(merged)} range={lo}..{hi}", flush=True)

        if consecutive >= args.max_consecutive_failures:
            print("provider circuit breaker: stopping after consecutive failures", flush=True)
            break
        if consecutive:
            cooldown = min(args.max_backoff, args.failure_backoff * (2 ** (consecutive - 1)))
            cooldown += random.uniform(0.0, args.jitter)
            print(f"provider cooldown {cooldown:.1f}s after {consecutive} consecutive failure(s)", flush=True)
            time.sleep(cooldown)
        else:
            time.sleep(max(0.0, args.sleep) + random.uniform(0.0, max(0.0, args.jitter)))

    manifest = {"start": str(start), "end": str(end), "sleep_seconds": args.sleep, "jitter_seconds": args.jitter,
                "attempted": attempted, "results": results}
    stamp = pd.Timestamp.utcnow().strftime("%Y%m%d_%H%M%S")
    path = MANIFEST_DIR / f"direct_minute_gap_{stamp}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = pd.Series([r["status"] for r in results]).value_counts().to_dict() if results else {}
    print("direct minute gap fill summary", counts, "manifest", path, flush=True)


if __name__ == "__main__":
    main()
