from __future__ import annotations

import pandas as pd

from five_experts_intraday_backtest_v2 import _asof_event_snapshot, load_index_daily_features


def test_event_pool_is_visible_only_after_pool_date() -> None:
    history = pd.DataFrame(
        {
            "event_date": [pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-02")],
            "event_type": ["limit_up", "broken_board"],
            "instrument": ["SZ000001", "SZ000002"],
            "board_days": [2, None],
            "board_count": [2, None],
            "em_hs": [3.0, 4.0],
            "em_zdp": [10.0, -1.0],
            "em_amount": [100.0, 200.0],
        }
    )
    before, before_date, _ = _asof_event_snapshot(
        pd.Timestamp("2026-07-01"), history, {}
    )
    assert before.empty
    assert before_date is None

    after, after_date, counts = _asof_event_snapshot(
        pd.Timestamp("2026-07-02"), history, {}
    )
    assert after_date == "2026-07-01"
    assert counts["limit_up"] == 1
    assert float(after.loc[after["instrument"] == "SZ000001", "prior_event_limit_up_stock"].iloc[0]) == 1.0
    assert float(after.loc[after["instrument"] == "SZ000001", "prior_event_board_days"].iloc[0]) == 2.0


def test_index_daily_cache_has_prior_only_derived_metrics() -> None:
    frame = load_index_daily_features()
    assert not frame.empty
    assert {"date", "index_ret1", "index_ret3", "index_ret5", "index_positive_ratio"}.issubset(frame.columns)
    assert pd.to_datetime(frame["date"]).is_monotonic_increasing
