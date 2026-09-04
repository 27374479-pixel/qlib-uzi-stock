"""Run the existing five-style intraday backtest on an explicit frozen universe.

This is intentionally a thin adapter: it does not change signal rules,
execution, costs or outcome calculations. It only forces every minute source
(Eastmoney, BaoStock and Sina fallback) through a point-in-time universe file.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import five_experts_intraday_backtest as base
from eastmoney_recent_backfill import instrument_from_code, normalize_code


def load_instruments(path: Path) -> set[str]:
    instruments: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        code = normalize_code(raw)
        if not code:
            continue
        instrument = instrument_from_code(code)
        if instrument:
            instruments.add(instrument.upper())
    if not instruments:
        raise ValueError(f"No instruments in {path}")
    return instruments


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run base intraday replay on an explicit frozen universe")
    parser.add_argument("--universe-file", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--min-history-days", type=int, default=base.BacktestConfig.min_history_days)
    parser.add_argument("--min-daily-bars", type=int, default=base.BacktestConfig.min_daily_bars)
    parser.add_argument("--signal-times", default=base.BacktestConfig.signal_times)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    allowed = load_instruments(args.universe_file)
    original_load_minutes = base.load_minutes

    def filtered_load_minutes(start, end, max_files=0, instruments=None):
        requested = allowed if instruments is None else allowed & {str(x).upper() for x in instruments}
        return original_load_minutes(start, end, max_files, requested)

    # Preserve the tested strategy engine verbatim; only inject the explicit
    # historical universe into its data loader.
    base.load_minutes = filtered_load_minutes
    sys.argv = [
        "five_experts_intraday_backtest.py",
        "--start", args.start,
        "--end", args.end,
        "--top-n", str(max(1, args.top_n)),
        "--min-history-days", str(max(3, args.min_history_days)),
        "--min-daily-bars", str(max(20, args.min_daily_bars)),
        "--signal-times", args.signal_times,
        "--universe", "cached",
        "--output", str(args.output),
    ]
    result = base.main()
    result.setdefault("methodology", {})["explicit_universe_file"] = str(args.universe_file)
    result["methodology"]["explicit_universe_instruments"] = len(allowed)
    # base.main already wrote the result; rewrite with the adapter metadata.
    import json
    args.output.write_text(json.dumps(base._json_safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    main()
