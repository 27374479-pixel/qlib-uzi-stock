from __future__ import annotations

import numpy as np
import pandas as pd

from five_experts_intraday_backtest import (
    BacktestConfig,
    _asof_snapshot,
    _entry_and_exit,
    build_daily_features,
    limit_ratio,
)


def _bars(instrument: str, date: str, base: float) -> pd.DataFrame:
    times = list(pd.date_range(f"{date} 09:35", periods=24, freq="5min")) + list(
        pd.date_range(f"{date} 13:05", periods=24, freq="5min")
    )
    close = np.linspace(base, base * 1.01, len(times))
    return pd.DataFrame(
        {
            "instrument": instrument,
            "datetime": times,
            "open": close,
            "high": close + 0.02,
            "low": close - 0.02,
            "close": close,
            "volume": 1000.0,
            "amount": 100000.0,
        }
    )


def test_asof_snapshot_does_not_change_when_future_bar_changes() -> None:
    prior = _bars("SZ000001", "2026-07-09", 10.0)
    current = _bars("SZ000001", "2026-07-10", 10.1)
    minutes = pd.concat([prior, current], ignore_index=True)
    daily = build_daily_features(minutes, min_daily_bars=40)
    before = _asof_snapshot(minutes, daily, pd.Timestamp("2026-07-10"), "09:45")

    changed = minutes.copy()
    changed.loc[changed["datetime"] == pd.Timestamp("2026-07-10 09:50"), "close"] = 99.0
    changed.loc[changed["datetime"] == pd.Timestamp("2026-07-10 09:50"), "high"] = 99.0
    after = _asof_snapshot(changed, daily, pd.Timestamp("2026-07-10"), "09:45")

    columns = ["current_close", "current_high", "cum_amount", "intraday_return", "market_breadth"]
    pd.testing.assert_frame_equal(before[columns], after[columns], check_dtype=False)


def test_entry_is_strictly_after_signal_bar() -> None:
    frame = pd.concat(
        [_bars("SZ000001", "2026-07-09", 10.0), _bars("SZ000001", "2026-07-10", 10.1), _bars("SZ000001", "2026-07-11", 10.2)],
        ignore_index=True,
    )
    outcome = _entry_and_exit(
        frame,
        pd.Timestamp("2026-07-10 09:45"),
        pd.Timestamp("2026-07-10"),
        10.0,
        0.10,
        [pd.Timestamp("2026-07-09"), pd.Timestamp("2026-07-10"), pd.Timestamp("2026-07-11")],
        BacktestConfig(),
    )
    assert outcome["entry_filled"] is True
    assert outcome["entry_datetime"] == pd.Timestamp("2026-07-10 09:50")
    assert outcome["exit_2d_filled"] is False
    assert outcome["exit_2d_reason"] == "forward_window_missing"


def test_limit_band_proxy_uses_exchange_board() -> None:
    assert limit_ratio("SZ000001") == 0.10
    assert limit_ratio("SZ300001") == 0.20
    assert limit_ratio("SH688001") == 0.20
