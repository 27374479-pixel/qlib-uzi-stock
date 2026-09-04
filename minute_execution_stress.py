"""Replay one fixed signal set under execution/cost stress scenarios.

Signals come from a completed strict minute backtest.  This script does not
re-rank or re-select stocks; it only replays those exact signal timestamps on
raw BaoStock 5-minute bars.  That isolates execution fragility from model
selection changes and makes delay/cost tests cheap enough to run together.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import PROJECT_ROOT

MINUTE_DIR = PROJECT_ROOT / "data_lake" / "raw" / "baostock" / "equity_5min"


@dataclass(frozen=True)
class Scenario:
    label: str
    delay_minutes: int
    cost_multiplier: float


SCENARIOS = (
    Scenario("baseline_reexec", 0, 1.0),
    Scenario("cost2x", 0, 2.0),
    Scenario("delay5", 5, 1.0),
    Scenario("delay10", 10, 1.0),
    Scenario("delay30", 30, 1.0),
)


def _round_tick(value: float) -> float:
    return float(np.round(float(value) / 0.01) * 0.01)


def _static_limit_ratio(instrument: str) -> float:
    code = str(instrument).upper().replace("SH", "").replace("SZ", "")
    return 0.20 if code.startswith(("300", "301")) else 0.10


def _load_status(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["instrument"] = frame["instrument"].astype(str).str.upper()
    frame["is_st"] = frame.get("is_st", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    frame["is_n"] = frame.get("is_n", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    return frame.dropna(subset=["date", "instrument"])


def _status_lookup(frame: pd.DataFrame) -> dict[tuple[str, pd.Timestamp], tuple[bool, bool]]:
    return {
        (str(row.instrument), pd.Timestamp(row.date)): (bool(row.is_st), bool(row.is_n))
        for row in frame[["instrument", "date", "is_st", "is_n"]].itertuples(index=False)
    }


def _load_minutes(instrument: str, cache: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if instrument in cache:
        return cache[instrument]
    path = MINUTE_DIR / f"{instrument}.parquet"
    if not path.exists():
        cache[instrument] = pd.DataFrame()
        return cache[instrument]
    try:
        frame = pd.read_parquet(path, columns=["instrument", "datetime", "open", "high", "low", "close", "volume", "amount"])
    except Exception:
        frame = pd.read_parquet(path)
    if frame.empty:
        cache[instrument] = frame
        return frame
    frame["instrument"] = frame.get("instrument", pd.Series(instrument, index=frame.index)).astype(str).str.upper()
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = (
        frame.dropna(subset=["datetime", "open", "high", "low", "close"])
        .drop_duplicates(["datetime"], keep="last")
        .sort_values("datetime")
        .reset_index(drop=True)
    )
    cache[instrument] = frame
    return frame


def _ratio(instrument: str, date: pd.Timestamp, status: dict[tuple[str, pd.Timestamp], tuple[bool, bool]]) -> float:
    is_st, _ = status.get((instrument, date.normalize()), (False, False))
    return 0.05 if is_st else _static_limit_ratio(instrument)


def _last_close_before(frame: pd.DataFrame, date: pd.Timestamp) -> float | None:
    prior = frame.loc[frame["datetime"].dt.normalize() < date.normalize()]
    if prior.empty:
        return None
    return float(prior.iloc[-1]["close"])


def _first_bar_on(frame: pd.DataFrame, date: pd.Timestamp) -> pd.Series | None:
    rows = frame.loc[frame["datetime"].dt.normalize() == date.normalize()]
    return None if rows.empty else rows.iloc[0]


def _entry_bar(frame: pd.DataFrame, signal_dt: pd.Timestamp, delay_minutes: int) -> pd.Series | None:
    threshold = signal_dt + pd.Timedelta(minutes=max(0, delay_minutes))
    rows = frame.loc[
        (frame["datetime"] > threshold)
        & (frame["datetime"].dt.normalize() == signal_dt.normalize())
    ]
    return None if rows.empty else rows.iloc[0]


def _replay_one(
    trade: dict[str, Any],
    frame: pd.DataFrame,
    trading_dates: list[pd.Timestamp],
    status: dict[tuple[str, pd.Timestamp], tuple[bool, bool]],
    scenario: Scenario,
    open_cost: float,
    close_cost: float,
) -> dict[str, Any]:
    result = dict(trade)
    instrument = str(trade.get("instrument", "")).upper()
    signal_dt = pd.Timestamp(trade["signal_datetime"])
    signal_date = pd.Timestamp(trade.get("signal_date", signal_dt)).normalize()
    entry = _entry_bar(frame, signal_dt, scenario.delay_minutes)
    if entry is None:
        result.update({"entry_filled": False, "entry_reason": "no_same_session_entry_after_delay"})
        for horizon in (1, 2, 5):
            result[f"return_{horizon}d"] = None
        return result

    previous_close = _last_close_before(frame, signal_date)
    if previous_close is None:
        result.update({"entry_filled": False, "entry_reason": "previous_close_missing"})
        return result
    entry_ratio = _ratio(instrument, signal_date, status)
    upper = _round_tick(previous_close * (1.0 + entry_ratio))
    lower = _round_tick(previous_close * (1.0 - entry_ratio))
    locked_up = bool(entry["open"] >= upper - 0.011 and entry["low"] >= upper - 0.011 and entry["high"] >= upper - 0.011)
    locked_down = bool(entry["open"] <= lower + 0.011 and entry["high"] <= lower + 0.011)
    if locked_up or locked_down:
        result.update(
            {
                "entry_filled": False,
                "entry_reason": "entry_locked_up" if locked_up else "entry_locked_down",
                "entry_datetime": entry["datetime"].isoformat(),
                "entry_open": float(entry["open"]),
            }
        )
        for horizon in (1, 2, 5):
            result[f"return_{horizon}d"] = None
        return result

    entry_price = float(entry["open"])
    result.update(
        {
            "entry_filled": True,
            "entry_reason": f"reexec_delay_{scenario.delay_minutes}m",
            "entry_datetime": entry["datetime"].isoformat(),
            "entry_open": entry_price,
        }
    )
    try:
        pos = trading_dates.index(signal_date)
    except ValueError:
        result["entry_filled"] = False
        result["entry_reason"] = "signal_date_not_in_status_calendar"
        return result

    for horizon in (1, 2, 5):
        target_pos = pos + horizon
        if target_pos >= len(trading_dates):
            result[f"exit_{horizon}d_filled"] = False
            result[f"exit_{horizon}d_reason"] = "forward_window_missing"
            result[f"return_{horizon}d"] = None
            continue
        exit_date = trading_dates[target_pos]
        exit_bar = _first_bar_on(frame, exit_date)
        if exit_bar is None:
            result[f"exit_{horizon}d_filled"] = False
            result[f"exit_{horizon}d_reason"] = "no_exit_bar"
            result[f"return_{horizon}d"] = None
            continue
        prev_exit_close = _last_close_before(frame, exit_date)
        if prev_exit_close is None:
            result[f"exit_{horizon}d_filled"] = False
            result[f"exit_{horizon}d_reason"] = "exit_previous_close_missing"
            result[f"return_{horizon}d"] = None
            continue
        exit_ratio = _ratio(instrument, exit_date, status)
        exit_lower = _round_tick(prev_exit_close * (1.0 - exit_ratio))
        exit_locked_down = bool(
            exit_bar["open"] <= exit_lower + 0.011
            and exit_bar["high"] <= exit_lower + 0.011
            and exit_bar["low"] <= exit_lower + 0.011
        )
        result[f"exit_{horizon}d_filled"] = not exit_locked_down
        result[f"exit_{horizon}d_reason"] = "first_bar_open" if not exit_locked_down else "exit_locked_down"
        result[f"exit_{horizon}d_date"] = exit_date.isoformat()
        result[f"exit_{horizon}d_open"] = float(exit_bar["open"])
        result[f"return_{horizon}d"] = (
            float(
                float(exit_bar["open"]) / entry_price
                - 1.0
                - open_cost * scenario.cost_multiplier
                - close_cost * scenario.cost_multiplier
            )
            if not exit_locked_down
            else None
        )
    return result


def _parity(original: pd.DataFrame, replay: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in (1, 5):
        column = f"return_{horizon}d"
        if column not in original or column not in replay:
            continue
        left = pd.to_numeric(original[column], errors="coerce")
        right = pd.to_numeric(replay[column], errors="coerce")
        mask = left.notna() & right.notna()
        diff = (left.loc[mask] - right.loc[mask]).abs()
        result[horizon] = {
            "comparable": int(mask.sum()),
            "mean_abs_diff": None if diff.empty else float(diff.mean()),
            "max_abs_diff": None if diff.empty else float(diff.max()),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay fixed minute signals under delay/cost stress")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--open-cost", type=float, default=0.0003)
    parser.add_argument("--close-cost", type=float, default=0.0013)
    args = parser.parse_args()

    payload = json.loads(args.baseline.read_text(encoding="utf-8"))
    trades = pd.DataFrame(payload.get("trades", []))
    status_frame = _load_status(args.status_file)
    status = _status_lookup(status_frame)
    trading_dates = sorted(pd.Timestamp(x) for x in status_frame["date"].drop_duplicates())
    cache: dict[str, pd.DataFrame] = {}
    args.output_dir.mkdir(parents=True, exist_ok=True)

    scenario_payloads: dict[str, dict[str, Any]] = {}
    for scenario in SCENARIOS:
        replay_rows: list[dict[str, Any]] = []
        for trade in payload.get("trades", []):
            instrument = str(trade.get("instrument", "")).upper()
            frame = _load_minutes(instrument, cache)
            if frame.empty:
                row = dict(trade)
                row.update({"entry_filled": False, "entry_reason": "minute_file_missing"})
                for horizon in (1, 2, 5):
                    row[f"return_{horizon}d"] = None
                replay_rows.append(row)
                continue
            replay_rows.append(
                _replay_one(trade, frame, trading_dates, status, scenario, args.open_cost, args.close_cost)
            )
        out = {
            "source_baseline": str(args.baseline),
            "scenario": {
                "label": scenario.label,
                "entry_delay_minutes": scenario.delay_minutes,
                "cost_multiplier": scenario.cost_multiplier,
                "open_cost_base": args.open_cost,
                "close_cost_base": args.close_cost,
                "dynamic_st_exit_limit": True,
                "signals_frozen": True,
            },
            "data_quality": payload.get("data_quality", {}),
            "methodology": payload.get("methodology", {}),
            "trades": replay_rows,
        }
        scenario_payloads[scenario.label] = out
        (args.output_dir / f"{scenario.label}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    baseline_replay = pd.DataFrame(scenario_payloads["baseline_reexec"]["trades"])
    audit = {
        "source_baseline": str(args.baseline),
        "signal_count": int(len(trades)),
        "unique_instruments_loaded": int(len(cache)),
        "parity_against_original": _parity(trades, baseline_replay),
        "scenario_files": {label: str(args.output_dir / f"{label}.json") for label in scenario_payloads},
    }
    (args.output_dir / "execution_stress_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
