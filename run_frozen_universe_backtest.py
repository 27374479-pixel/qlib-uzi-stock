"""Run the existing five-style intraday backtest on an explicit frozen universe.

This is intentionally a thin adapter: signal rules remain in
``five_experts_intraday_backtest``. The adapter injects (1) an explicit
point-in-time universe, (2) optional historical daily ST/N status, (3) an
optional transaction-cost multiplier and (4) an execution-delay stress test.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

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


def load_bad_status_keys(path: Path | None) -> set[tuple[str, pd.Timestamp]]:
    if path is None:
        return set()
    frame = pd.read_parquet(path)
    if frame.empty:
        return set()
    frame["instrument"] = frame["instrument"].astype(str).str.upper()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    is_st = frame.get("is_st", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    is_n = frame.get("is_n", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    bad = frame.loc[(is_st | is_n) & frame["date"].notna(), ["instrument", "date"]]
    return {(str(row.instrument), pd.Timestamp(row.date)) for row in bad.itertuples(index=False)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run base intraday replay on an explicit frozen universe")
    parser.add_argument("--universe-file", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, default=None)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--min-history-days", type=int, default=base.BacktestConfig.min_history_days)
    parser.add_argument("--min-daily-bars", type=int, default=base.BacktestConfig.min_daily_bars)
    parser.add_argument("--signal-times", default=base.BacktestConfig.signal_times)
    parser.add_argument("--cost-multiplier", type=float, default=1.0)
    parser.add_argument(
        "--entry-delay-minutes",
        type=int,
        default=0,
        help="Additional delay after the original signal timestamp before selecting the next 5m bar",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    allowed = load_instruments(args.universe_file)
    bad_status_keys = load_bad_status_keys(args.status_file)
    original_load_minutes = base.load_minutes
    original_config = base.BacktestConfig
    original_entry_and_exit = base._entry_and_exit

    def filtered_load_minutes(start, end, max_files=0, instruments=None):
        requested = allowed if instruments is None else allowed & {str(x).upper() for x in instruments}
        minutes = original_load_minutes(start, end, max_files, requested)
        if minutes.empty or not bad_status_keys:
            return minutes
        dates = pd.to_datetime(minutes["datetime"], errors="coerce").dt.normalize()
        keys = list(zip(minutes["instrument"].astype(str).str.upper(), dates))
        keep = pd.Series([key not in bad_status_keys for key in keys], index=minutes.index)
        return minutes.loc[keep].reset_index(drop=True)

    multiplier = max(0.0, float(args.cost_multiplier))
    delay_minutes = max(0, int(args.entry_delay_minutes))

    def stressed_config(**kwargs):
        return original_config(
            open_cost=original_config.open_cost * multiplier,
            close_cost=original_config.close_cost * multiplier,
            **kwargs,
        )

    # base.parse_args reads defaults from BacktestConfig as class attributes.
    for name in (
        "start", "end", "top_n", "min_history_days", "min_daily_bars", "signal_times",
        "open_cost", "close_cost", "max_files", "universe",
    ):
        setattr(stressed_config, name, getattr(original_config, name))

    def delayed_entry_and_exit(
        instrument_frame,
        signal_datetime,
        signal_date,
        signal_previous_close,
        limit_ratio_value,
        trading_dates,
        config,
    ):
        shifted = pd.Timestamp(signal_datetime) + pd.Timedelta(minutes=delay_minutes)
        outcome = original_entry_and_exit(
            instrument_frame,
            shifted,
            signal_date,
            signal_previous_close,
            limit_ratio_value,
            trading_dates,
            config,
        )
        entry_dt = outcome.get("entry_datetime")
        if entry_dt is not None and pd.Timestamp(entry_dt).normalize() != pd.Timestamp(signal_date).normalize():
            return {
                "entry_filled": False,
                "entry_reason": "delay_crossed_signal_session",
                "entry_datetime": entry_dt,
                "entry_open": outcome.get("entry_open"),
            }
        if delay_minutes and outcome.get("entry_filled"):
            outcome["entry_reason"] = f"next_bar_open_after_{delay_minutes}m_delay"
        return outcome

    # Preserve the tested strategy engine verbatim; inject only data-universe
    # eligibility, transaction-cost stress and the explicit execution delay.
    base.load_minutes = filtered_load_minutes
    base.BacktestConfig = stressed_config
    base._entry_and_exit = delayed_entry_and_exit
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
    result["methodology"]["daily_status_file"] = None if args.status_file is None else str(args.status_file)
    result["methodology"]["daily_st_n_exclusion_keys"] = len(bad_status_keys)
    result["methodology"]["cost_multiplier"] = multiplier
    result["methodology"]["entry_delay_minutes"] = delay_minutes
    # base.main already wrote the result; rewrite with the adapter metadata.
    args.output.write_text(json.dumps(base._json_safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    main()
