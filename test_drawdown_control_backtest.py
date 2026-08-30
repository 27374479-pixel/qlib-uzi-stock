import numpy as np

from drawdown_control_backtest import PortfolioSpec, lagged_exposure


def test_volatility_control_uses_only_supplied_lagged_returns():
    spec = PortfolioSpec("test", (("x", 1.0),), target_volatility=0.10, minimum_vol_history=3)
    history = [0.02, -0.03, 0.01]
    exposure, estimated, _ = lagged_exposure(spec, history, [], 12.0)
    expected = min(1.0, max(0.20, 0.10 / (np.std(history, ddof=1) * np.sqrt(12.0))))
    assert np.isclose(exposure, expected)
    assert estimated > 0


def test_negative_lagged_trend_caps_exposure():
    spec = PortfolioSpec("test", (("x", 1.0),), trend_lookback=3, defensive_exposure=0.35)
    exposure, _, trend = lagged_exposure(spec, [], [0.01, -0.04, 0.01], 12.0)
    assert trend < 0
    assert exposure == 0.35


def test_current_period_cannot_change_current_exposure():
    spec = PortfolioSpec("test", (("x", 1.0),), target_volatility=0.10, trend_lookback=3, minimum_vol_history=3)
    past = [0.01, -0.02, 0.03]
    benchmark = [0.02, -0.01, 0.01]
    first = lagged_exposure(spec, past, benchmark, 12.0)
    second = lagged_exposure(spec, past, benchmark, 12.0)
    assert first == second
