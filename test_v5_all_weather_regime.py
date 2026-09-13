import pandas as pd
import pytest

import v5_all_weather_regime as v5


def _market_frame(n=30, breadth=0.2, breadth5=0.1, money_effect=0.01, weak=False):
    dates = pd.bdate_range('2024-01-02', periods=n)
    return pd.DataFrame({
        'date': dates,
        'breadth': [breadth] * n,
        'breadth5': [breadth5] * n,
        'money_effect': [money_effect] * n,
        'weak_market': [weak] * n,
    })


def test_regime_is_shifted_from_signal_date_to_next_trade_date():
    frame = _market_frame()
    table = v5.build_regime_table(frame)
    assert table.iloc[20].signal_date == frame.iloc[20].date
    assert table.iloc[20].trade_date == frame.iloc[21].date
    assert table.iloc[20].regime == v5.REGIME_RISK_ON


def test_risk_off_precedence_for_weak_market():
    frame = _market_frame()
    frame.loc[20, 'weak_market'] = True
    table = v5.build_regime_table(frame)
    row = table.loc[table.signal_date.eq(frame.loc[20, 'date'])].iloc[0]
    assert row.regime == v5.REGIME_RISK_OFF


def test_negative_slow_breadth_is_risk_off():
    frame = _market_frame(breadth=-0.2, breadth5=0.1, money_effect=0.01, weak=False)
    table = v5.build_regime_table(frame)
    observed = table.loc[table.regime_inputs_observed]
    assert not observed.empty
    assert observed.regime.eq(v5.REGIME_RISK_OFF).all()


def test_mixed_sign_state_is_neutral_not_parameter_searched():
    frame = _market_frame(breadth=0.2, breadth5=0.1, money_effect=-0.01, weak=False)
    table = v5.build_regime_table(frame)
    observed = table.loc[table.regime_inputs_observed]
    assert not observed.empty
    assert observed.regime.eq(v5.REGIME_NEUTRAL).all()


def test_missing_inputs_are_neutral():
    frame = _market_frame()
    frame.loc[20, 'money_effect'] = float('nan')
    table = v5.build_regime_table(frame)
    row = table.loc[table.signal_date.eq(frame.loc[20, 'date'])].iloc[0]
    assert not bool(row.regime_inputs_observed)
    assert row.regime == v5.REGIME_NEUTRAL


def test_inconsistent_same_day_market_state_hard_fails():
    frame = _market_frame()
    duplicate = frame.iloc[[20]].copy()
    duplicate['breadth5'] = -0.3
    frame = pd.concat([frame, duplicate], ignore_index=True)
    with pytest.raises(RuntimeError, match='vary within the same date'):
        v5.build_regime_table(frame)


def test_router_invests_only_risk_on_and_keeps_other_days_cash():
    dates = pd.bdate_range('2024-02-01', periods=3)
    x02 = pd.Series([0.10, -0.20, 0.30], index=dates, name='x02_return')
    regimes = pd.DataFrame({
        'signal_date': pd.bdate_range('2024-01-31', periods=3),
        'trade_date': dates,
        'breadth': [0.2, 0.0, -0.2],
        'breadth5': [0.1, 0.0, -0.1],
        'breadth20': [0.1, 0.1, -0.1],
        'money_effect': [0.01, 0.0, -0.01],
        'weak_market': [False, False, True],
        'regime_inputs_observed': [True, True, True],
        'regime': [v5.REGIME_RISK_ON, v5.REGIME_NEUTRAL, v5.REGIME_RISK_OFF],
    })
    routed = v5.route_x02(x02, regimes)
    assert routed.allocation.tolist() == [1.0, 0.0, 0.0]
    assert routed.routed_return.tolist() == pytest.approx([0.10, 0.0, 0.0])


def test_missing_route_state_defaults_to_cash():
    dates = pd.bdate_range('2024-02-01', periods=2)
    x02 = pd.Series([0.10, 0.20], index=dates)
    regimes = pd.DataFrame({
        'signal_date': [pd.Timestamp('2024-01-31')],
        'trade_date': [dates[0]],
        'regime_inputs_observed': [True],
        'regime': [v5.REGIME_RISK_ON],
    })
    routed = v5.route_x02(x02, regimes)
    assert routed.iloc[0].allocation == 1.0
    assert routed.iloc[1].allocation == 0.0
    assert bool(routed.iloc[1].missing_route_state)


def test_corrected_drawdown_includes_first_day_loss():
    dates = pd.bdate_range('2024-01-02', periods=3)
    result = v5.metrics(pd.Series([-0.20, 0.10, 0.10], index=dates))
    assert result['max_drawdown_corrected'] == pytest.approx(-0.20)


def test_future_market_change_does_not_change_prior_trade_route():
    frame = _market_frame()
    first = v5.build_regime_table(frame)
    target_signal = frame.loc[20, 'date']
    target_trade = frame.loc[21, 'date']
    before = first.loc[first.trade_date.eq(target_trade), 'regime'].iloc[0]

    changed = frame.copy()
    changed.loc[21:, ['breadth', 'breadth5', 'money_effect']] = -0.9
    changed.loc[21:, 'weak_market'] = True
    second = v5.build_regime_table(changed)
    after = second.loc[second.trade_date.eq(target_trade), 'regime'].iloc[0]

    assert before == after == v5.REGIME_RISK_ON
    assert first.loc[first.signal_date.eq(target_signal), 'trade_date'].iloc[0] == target_trade
