import pandas as pd

from event_role_minute_execution import _find_trigger


def test_trigger_requires_divergence_before_reclaim():
    times = pd.date_range("2026-08-24 09:35", periods=6, freq="5min")
    day = pd.DataFrame(
        {
            "datetime": times,
            "open": [10.0, 9.95, 9.86, 9.90, 10.02, 10.10],
            "high": [10.02, 9.98, 9.92, 10.01, 10.12, 10.15],
            "low": [9.96, 9.88, 9.82, 9.88, 10.00, 10.08],
            "close": [9.96, 9.90, 9.88, 10.00, 10.10, 10.12],
            "vwap": [9.99, 9.95, 9.91, 9.94, 9.98, 10.01],
            "intraday_ret": [-0.004, -0.01, -0.012, 0.0, 0.01, 0.012],
            "peer_n": [4] * 6,
            "peer_positive_n": [3] * 6,
            "peer_median_ret": [0.01] * 6,
            "market_median_ret": [0.0] * 6,
        }
    )
    position, details = _find_trigger(day, 10.0)
    assert position == 3
    assert details["confirm_position"] == 4


def test_no_trigger_without_peer_support():
    times = pd.date_range("2026-08-24 09:35", periods=6, freq="5min")
    day = pd.DataFrame(
        {
            "datetime": times,
            "open": [10.0, 9.95, 9.86, 9.90, 10.02, 10.10],
            "high": [10.02, 9.98, 9.92, 10.01, 10.12, 10.15],
            "low": [9.96, 9.88, 9.82, 9.88, 10.00, 10.08],
            "close": [9.96, 9.90, 9.88, 10.00, 10.10, 10.12],
            "vwap": [9.99, 9.95, 9.91, 9.94, 9.98, 10.01],
            "intraday_ret": [-0.004, -0.01, -0.012, 0.0, 0.01, 0.012],
            "peer_n": [4] * 6,
            "peer_positive_n": [1] * 6,
            "peer_median_ret": [-0.01] * 6,
            "market_median_ret": [0.0] * 6,
        }
    )
    position, details = _find_trigger(day, 10.0)
    assert position is None
    assert details["reject_reason"] == "no_divergence_stabilization"
