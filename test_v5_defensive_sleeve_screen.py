import numpy as np
import pandas as pd

import v5_defensive_sleeve_screen as d01


def _frame():
    return pd.DataFrame({
        'date': pd.to_datetime(['2024-01-02'] * 5),
        'clean_mom60': [0.1] * 5,
        'clean_mom60_rank': [0.80, 0.80, 0.80, 0.80, 0.60],
        'hit_count20': [0, 1, 0, 2, 0],
        'vol20_rank': [0.20, 0.70, 0.50, 0.20, 0.20],
        'entry_filled': [True, True, True, True, True],
    })


def test_masks_use_frozen_low_and_high_vol_bands():
    selected, control = d01.d01_masks(_frame())
    assert selected.tolist() == [True, False, False, False, False]
    assert control.tolist() == [False, True, False, False, False]
    assert not bool((selected & control).any())


def test_nonpositive_clean_momentum_is_excluded():
    frame = _frame()
    frame.loc[0, 'clean_mom60'] = 0.0
    selected, _ = d01.d01_masks(frame)
    assert not bool(selected.iloc[0])


def test_unfilled_next_open_is_excluded():
    frame = _frame()
    frame.loc[0, 'entry_filled'] = False
    selected, _ = d01.d01_masks(frame)
    assert not bool(selected.iloc[0])


def _segment(mean_return=.01, excess=.005, diff=.004, lower=.001, n=200, days=80):
    return {
        'selected': {'n': n, 'active_days': days, 'mean_return': mean_return, 'mean_market_excess': excess},
        'paired': {'selected_minus_control': diff, 'bootstrap95_expected_signed_difference': [lower, .01]},
    }


def test_qualification_requires_both_segments_to_pass():
    result = d01.qualification_from_primary(_segment(), _segment())
    assert result['qualified_for_minute_replay'] is True
    assert result['status'] == 'QUALIFIED_FOR_MINUTE_REPLAY'
    assert result['portfolio_combination_authorized'] is False


def test_negative_development_return_rejects_without_retuning():
    result = d01.qualification_from_primary(_segment(mean_return=-.001), _segment())
    assert result['qualified_for_minute_replay'] is False
    assert result['status'] == 'REJECTED'
    assert any('development_2021_2023' in reason for reason in result['reasons'])


def test_nonpositive_bootstrap_lower_bound_rejects():
    result = d01.qualification_from_primary(_segment(lower=0.0), _segment())
    assert result['qualified_for_minute_replay'] is False
    assert any('bootstrap' in reason for reason in result['reasons'])


def test_insufficient_later_sample_rejects():
    result = d01.qualification_from_primary(_segment(), _segment(n=99, days=39))
    assert result['qualified_for_minute_replay'] is False
    assert any('historical_later_2024_plus' in reason for reason in result['reasons'])


def test_vol20_is_past_only_rolling_statistic_and_clean_rank_is_derived():
    dates = pd.bdate_range('2024-01-02', periods=20)
    returns = np.linspace(-.01, .01, 20)
    close = 100 * (1 + returns)
    preclose = np.full(20, 100.0)
    frame = pd.DataFrame({
        'instrument': ['A'] * 20,
        'date': dates,
        'close': close,
        'preclose': preclose,
        'clean_mom60': np.linspace(.01, .20, 20),
    })
    first = d01.add_d01_features(frame)
    before = float(first.loc[18, 'vol20'])
    assert first['clean_mom60_rank'].notna().all()

    changed = frame.copy()
    changed.loc[19, 'close'] = 200.0
    changed.loc[19, 'clean_mom60'] = 9.0
    second = d01.add_d01_features(changed)
    after = float(second.loc[18, 'vol20'])
    assert before == after
