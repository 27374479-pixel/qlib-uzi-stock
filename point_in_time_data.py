"""Point-in-time auxiliary data collection for the automatic factor factory.

BaoStock is used for historical tradability, ST, valuation and turnover fields.
Raw provider responses are retained per instrument so collection is resumable and
future corrections can be audited.  Current-only industry classifications are not
mixed into the historical dataset.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import baostock as bs
import numpy as np
import pandas as pd

from config import PROJECT_ROOT, QLIB_DATA_DIR


DATA_LAKE_DIR = PROJECT_ROOT / "data_lake"
BAOSTOCK_DAILY_DIR = DATA_LAKE_DIR / "raw" / "baostock" / "equity_daily"
MANIFEST_DIR = DATA_LAKE_DIR / "manifests"

BAOSTOCK_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,"
    "tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
)
NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "turn",
    "pctChg",
    "peTTM",
    "pbMRQ",
    "psTTM",
    "pcfNcfTTM",
]


@dataclass(frozen=True)
class CollectionConfig:
    start: str = "2014-01-01"
    end: str = "2026-07-17"
    market: str = "csi800"
    retry_count: int = 3
    retry_delay_seconds: float = 1.0


def qlib_to_baostock(instrument: str) -> str:
    normalized = instrument.strip().upper()
    if normalized.startswith("SH") and len(normalized) == 8:
        return f"sh.{normalized[2:]}"
    if normalized.startswith("SZ") and len(normalized) == 8:
        return f"sz.{normalized[2:]}"
    raise ValueError(f"BaoStock does not support instrument {instrument!r}")


def membership_instruments(market: str) -> list[str]:
    path = QLIB_DATA_DIR / "instruments" / f"{market}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Missing Qlib membership file: {path}")
    instruments = {line.split("\t", 1)[0].strip().upper() for line in path.read_text().splitlines() if line.strip()}
    return sorted(instrument for instrument in instruments if instrument.startswith(("SH", "SZ")))


def normalize_baostock_daily(rows: list[list[str]], fields: list[str], instrument: str) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=fields)
    if frame.empty:
        return frame
    frame.insert(0, "instrument", instrument)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["trade_status"] = pd.to_numeric(frame.pop("tradestatus"), errors="coerce").astype("Int8")
    frame["is_st"] = pd.to_numeric(frame.pop("isST"), errors="coerce").astype("Int8")
    frame["adjust_flag"] = pd.to_numeric(frame.pop("adjustflag"), errors="coerce").astype("Int8")
    frame = frame.rename(
        columns={
            "turn": "turnover_rate_pct",
            "pctChg": "return_pct",
            "peTTM": "pe_ttm",
            "pbMRQ": "pb_mrq",
            "psTTM": "ps_ttm",
            "pcfNcfTTM": "pcf_ncf_ttm",
        }
    )
    # BaoStock volume is in shares and turnover is a percentage.  This is an
    # estimate because provider rounding and corporate events can cause noise.
    valid_turnover = frame["turnover_rate_pct"].where(frame["turnover_rate_pct"] > 1e-6)
    frame["float_shares_est"] = frame["volume"] / (valid_turnover / 100.0)
    frame["float_market_cap_est"] = frame["float_shares_est"] * frame["close"]
    frame["source"] = "baostock"
    frame["knowledge_date"] = frame["date"]
    return frame.dropna(subset=["date"]).drop_duplicates(["instrument", "date"], keep="last").sort_values("date")


def fetch_symbol(instrument: str, config: CollectionConfig) -> pd.DataFrame:
    code = qlib_to_baostock(instrument)
    result = bs.query_history_k_data_plus(
        code,
        BAOSTOCK_FIELDS,
        start_date=config.start,
        end_date=config.end,
        frequency="d",
        adjustflag="3",
    )
    if result.error_code != "0":
        raise RuntimeError(f"BaoStock {instrument}: {result.error_code} {result.error_msg}")
    rows = []
    while result.next():
        rows.append(result.get_row_data())
    return normalize_baostock_daily(rows, result.fields, instrument)


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.parquet")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def validate_frame(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"rows": 0, "valid": False, "reason": "empty"}
    duplicate_rows = int(frame.duplicated(["instrument", "date"]).sum())
    traded = frame["trade_status"].eq(1)
    positive_price = frame["close"].gt(0) | ~traded
    float_cap_valid = frame.loc[frame["turnover_rate_pct"].gt(0), "float_market_cap_est"].gt(0)
    return {
        "rows": len(frame),
        "first_date": str(frame["date"].min().date()),
        "last_date": str(frame["date"].max().date()),
        "duplicate_rows": duplicate_rows,
        "trading_price_valid_rate": float(positive_price.mean()),
        "trade_status_coverage": float(frame["trade_status"].notna().mean()),
        "st_coverage": float(frame["is_st"].notna().mean()),
        "turnover_coverage": float(frame["turnover_rate_pct"].notna().mean()),
        "valuation_coverage": float(frame[["pe_ttm", "pb_mrq", "ps_ttm"]].notna().any(axis=1).mean()),
        "float_cap_valid_rate": float(float_cap_valid.mean()) if len(float_cap_valid) else None,
        "valid": duplicate_rows == 0 and bool(positive_price.all()),
    }


def collect(
    config: CollectionConfig,
    instruments: list[str],
    resume: bool = True,
) -> dict:
    BAOSTOCK_DAILY_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    successes: list[dict] = []
    failures: list[dict] = []
    skipped = 0
    started = datetime.now(timezone.utc)
    try:
        for number, instrument in enumerate(instruments, 1):
            destination = BAOSTOCK_DAILY_DIR / f"{instrument}.parquet"
            if resume and destination.exists():
                skipped += 1
                continue
            error = None
            for attempt in range(1, config.retry_count + 1):
                try:
                    frame = fetch_symbol(instrument, config)
                    quality = validate_frame(frame)
                    if not quality["valid"]:
                        raise ValueError(f"quality check failed: {quality}")
                    _atomic_parquet(frame, destination)
                    successes.append({"instrument": instrument, **quality})
                    error = None
                    break
                except Exception as exc:  # provider/network errors are recorded and retried
                    error = str(exc)
                    if attempt < config.retry_count:
                        # BaoStock anonymous sessions can be invalidated by a
                        # second login or a dropped socket.  Re-authenticate on
                        # every retry so a long backfill can recover in place.
                        recovery = bs.login()
                        if recovery.error_code != "0":
                            error = f"{error}; reconnect failed: {recovery.error_msg}"
                        time.sleep(config.retry_delay_seconds * attempt)
            if error is not None:
                failures.append({"instrument": instrument, "error": error})
            if number == 1 or number % 25 == 0:
                print(
                    f"  auxiliary data {number}/{len(instruments)} new={len(successes)} "
                    f"skipped={skipped} failed={len(failures)}",
                    flush=True,
                )
    finally:
        bs.logout()

    finished = datetime.now(timezone.utc)
    manifest = {
        "provider": "BaoStock",
        "dataset": "historical equity daily auxiliary fields",
        "point_in_time_policy": "daily market fields use their trading date; current-only industry is excluded",
        "config": asdict(config),
        "requested_instruments": len(instruments),
        "downloaded": len(successes),
        "skipped_existing": skipped,
        "failed": failures,
        "quality": aggregate_quality(successes),
        "started_utc": started.isoformat(),
        "finished_utc": finished.isoformat(),
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = MANIFEST_DIR / f"baostock_{stamp}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest: {manifest_path}", flush=True)
    return manifest


def aggregate_quality(records: list[dict]) -> dict:
    if not records:
        return {}
    return {
        "rows": int(sum(record["rows"] for record in records)),
        "mean_trade_status_coverage": float(np.mean([record["trade_status_coverage"] for record in records])),
        "mean_st_coverage": float(np.mean([record["st_coverage"] for record in records])),
        "mean_turnover_coverage": float(np.mean([record["turnover_coverage"] for record in records])),
        "mean_valuation_coverage": float(np.mean([record["valuation_coverage"] for record in records])),
        "mean_float_cap_valid_rate": float(
            np.mean([record["float_cap_valid_rate"] for record in records if record["float_cap_valid_rate"] is not None])
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect point-in-time auxiliary A-share data")
    parser.add_argument("--market", default=CollectionConfig.market)
    parser.add_argument("--start", default=CollectionConfig.start)
    parser.add_argument("--end", default=CollectionConfig.end)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> dict:
    args = parse_args()
    config = CollectionConfig(start=args.start, end=args.end, market=args.market)
    instruments = [item.upper() for item in args.symbols] if args.symbols else membership_instruments(args.market)
    if args.limit is not None:
        instruments = instruments[: args.limit]
    print(f"Collecting {len(instruments)} instruments for {config.start}..{config.end}", flush=True)
    return collect(config, instruments, resume=not args.no_resume)


if __name__ == "__main__":
    main()
