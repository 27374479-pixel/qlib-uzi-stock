"""Audit fixed-universe minute coverage without fabricating missing rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import long_uzi_state_backtest as model


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit fixed CSI800 minute coverage")
    parser.add_argument("--start", default="20240102")
    parser.add_argument("--end", default="20260824")
    parser.add_argument("--universe", choices=["csi300_start", "csi500_start", "csi800_start"], default="csi800_start")
    parser.add_argument("--universe-asof", default="20240102")
    parser.add_argument("--output", default="output/minute_coverage_latest.json")
    args = parser.parse_args()
    start = pd.to_datetime(args.start, format="%Y%m%d").normalize()
    end = pd.to_datetime(args.end, format="%Y%m%d").normalize()
    instruments = sorted(model._fixed_universe(args.universe, args.universe_asof))
    rows = []
    for instrument in instruments:
        path = model.BAOSTOCK_MINUTE_DIR / f"{instrument}.parquet"
        item = {"instrument": instrument, "path": str(path), "exists": path.exists()}
        if path.exists():
            try:
                frame = pd.read_parquet(path, columns=["datetime"])
                dates = pd.to_datetime(frame["datetime"], errors="coerce").dropna()
                item.update(
                    {
                        "rows": int(len(dates)),
                        "actual_start": str(dates.min()) if not dates.empty else None,
                        "actual_end": str(dates.max()) if not dates.empty else None,
                        "complete_requested_window": bool(
                            not dates.empty
                            and dates.min().normalize() <= start
                            and dates.max().normalize() >= end - pd.Timedelta(days=4)
                        ),
                    }
                )
            except Exception as exc:
                item["error"] = str(exc)
        rows.append(item)
    frame = pd.DataFrame(rows)
    complete_series = (
        frame["complete_requested_window"].astype("boolean").fillna(False)
        if "complete_requested_window" in frame
        else pd.Series(False, index=frame.index, dtype="boolean")
    )
    result = {
        "universe": args.universe,
        "universe_asof": args.universe_asof,
        "requested_start": str(start.date()),
        "requested_end": str(end.date()),
        "expected": int(len(frame)),
        "present": int(frame["exists"].sum()),
        "complete": int(complete_series.sum()),
        "missing": int((~frame["exists"]).sum()),
        "rows": rows,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(model._safe_json(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("expected", "present", "complete", "missing")}, ensure_ascii=False))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
