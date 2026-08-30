import numpy as np
import pandas as pd

from yangjia_expectation_pressure_backtest import (
    Config,
    execute_target,
    exposure_for,
    market_sentiment,
    signal_dates,
)


def test_signal_dates_reserve_two_forward_sessions():
    cal = pd.date_range("2025-01-01", periods=6, freq="D")
    dates = signal_dates(cal, Config(start="2025-01-01", end="2025-01-06", rebalance_step=1))
    assert dates[-1] == pd.Timestamp("2025-01-04")
    assert len(dates) == 4


def test_signal_dates_honor_rebalance_step():
    cal = pd.date_range("2025-01-01", periods=12, freq="D")
    dates = signal_dates(cal, Config(start="2025-01-01", end="2025-01-12", rebalance_step=5))
    assert dates == [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-06")]


def test_market_sentiment_is_bounded():
    frame = pd.DataFrame(
        {
            "ret_1": np.linspace(-0.08, 0.08, 20),
            "ret_5": np.linspace(-0.20, 0.20, 20),
            "ret_20": np.linspace(-0.30, 0.30, 20),
            "volume_ratio": np.ones(20),
        }
    )
    result = market_sentiment(frame)
    assert 0.0 <= result["sentiment_score"] <= 1.0
    assert 0.0 <= result["advance_ratio"] <= 1.0


def test_exposure_reduces_in_weak_state():
    sentiment = {"sentiment_score": 0.25, "advance_ratio": 0.25}
    assert exposure_for(sentiment, "weak", previous_score=0.40) == 0.10


def test_blocked_order_preserves_old_position_but_missing_member_is_removed():
    snapshot = pd.DataFrame(
        {
            "entry_blocked": [True, False, False],
        },
        index=["SH600000", "SH600001", "SH600002"],
    )
    previous = {"SH600000": 0.5, "SH600099": 0.5}
    desired = {"SH600000": 0.0, "SH600001": 0.5, "SH600002": 0.5}
    actual, blocked = execute_target(desired, previous, snapshot)
    assert actual["SH600000"] == 0.5
    assert actual["SH600001"] == 0.25
    assert actual["SH600002"] == 0.25
    assert "SH600099" not in actual
    assert blocked == 1
