from __future__ import annotations

import pandas as pd

import four_experts_cross_enhanced_backtest as cross


def _asof_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "market_phase": ["neutral"],
            "clock_bucket": ["morning"],
            "cutoff": ["09:45"],
            "prior_daily_fear": [False],
            "prior_market_breadth": [0.05],
            "prior_market_ret3": [0.01],
            "prior_market_down_ratio": [0.20],
            "index_supportive": [True],
            "index_risk_contraction": [False],
            "prior_event_theme": [""],
            "prior_event_data_available": [False],
            "prior_event_limit_up_stock": [0],
            "prior_event_previous_limit_up_stock": [0],
            "prior_event_board_days": [0],
            "prior_prior_limit_up5": [0],
            "group_attack": [True],
            "group_n": [8],
            "group_breadth": [0.25],
            "group_return_median": [0.01],
            "group_amount_median": [1.2],
            "group_relative_return": [0.01],
            "group_intraday_rank": [0.95],
            "rank_intraday": [0.95],
            "group_prior10_rank": [0.95],
            "prior_ret10": [0.05],
            "prior_ret5": [0.03],
            "prior_ret1": [0.02],
            "gap_to_upper": [-0.02],
            "from_high": [-0.01],
            "intraday_return": [0.03],
            "from_open": [0.01],
            "amount_ratio_asof": [1.2],
            "locked_upper": [False],
            "market_breadth": [0.05],
            "market_down_ratio_2": [0.20],
            "broken_ratio": [0.20],
            "market_transition": [False],
            "collective_oversold": [False],
            "collective_stabilizing": [True],
            "reward_risk_proxy": [2.0],
            "recovery_from_low": [0.02],
            "late_momentum_30m": [0.003],
            "group_stabilizing": [True],
            "group_prior10_median": [0.03],
            "group_up_ratio_2": [0.5],
            "group_recovery_rank": [0.8],
            "prior_event_board_quality": [0.6],
            "board_quality": [0.6],
            "board_stage": ["charging"],
            "current_high": [10.0],
            "upper_limit": [10.1],
            "last_bar_high": [10.0],
            "board_level_proxy": [1.0],
        }
    )


def test_cross_rules_ignore_future_outcome_columns() -> None:
    before = _asof_frame()
    after = before.copy()
    after["entry_open"] = [999.0]
    after["return_1d"] = [999.0]
    after["return_2d"] = [-999.0]
    after["return_5d"] = [999.0]
    after["exit_1d_reason"] = ["future"]
    after["exit_2d_reason"] = ["future"]
    after["exit_5d_reason"] = ["future"]

    for style in cross.STYLES:
        expected = cross.apply_cross_rule(before, style)
        actual = cross.apply_cross_rule(after, style)
        for left, right in zip(expected, actual):
            pd.testing.assert_series_equal(left, right, check_dtype=False)
