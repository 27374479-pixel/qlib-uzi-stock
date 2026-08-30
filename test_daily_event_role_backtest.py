import pandas as pd

from daily_event_role_backtest import _tick_round, limit_ratio


def test_limit_ratio_respects_chinext_reform_date():
    dates = pd.Series(pd.to_datetime(["2020-08-21", "2020-08-24"]))
    values = limit_ratio("SZ300001", dates)
    assert values.tolist() == [0.10, 0.20]


def test_star_market_is_twenty_percent():
    dates = pd.Series(pd.to_datetime(["2019-07-22", "2024-01-02"]))
    assert limit_ratio("SH688001", dates).tolist() == [0.20, 0.20]


def test_tick_round_is_half_up():
    values = pd.Series([10.005, 10.0049, 9.995])
    assert _tick_round(values).tolist() == [10.01, 10.00, 10.00]
