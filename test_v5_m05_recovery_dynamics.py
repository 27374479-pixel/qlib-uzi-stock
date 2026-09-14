import numpy as np
import pandas as pd
import pytest

import v5_m05_recovery_dynamics as m05


def _tape() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"]),
            "universe_n": [100, 100, 100],
            "advance_count": [20, 35, 55],
            "decline_count": [70, 55, 35],
            "limit_down_count": [8, 5, 1],
            "seal_count": [4, 6, 10],
            "broken_ratio": [0.70, 0.50, 0.25],
            "multi_board_count": [1, 2, 4],
            "prior_seal_mean_return": [np.nan, -0.03, 0.02],
            "prior_multi_board_mean_return": [np.nan, np.nan, 0.01],
        }
    )


def _dispersion() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"]),
            "known_industry_n": [20, 20, 20],
            "positive_industry_ratio": [0.20, 0.40, 0.65],
            "seal_industry_n": [2, 4, 7],
            "first_board_industry_n": [1, 3, 6],
            "multi_board_industry_n": [1, 1, 3],
            "seal_hhi": [0.80, 0.55, 0.35],
            "first_board_hhi": [1.00, 0.70, 0.40],
            "multi_board_hhi": [1.00, 1.00, 0.50],
        }
    )


def test_levels_and_one_session_differences_are_exact():
    frame = m05.build_recovery_dynamics(_tape(), _dispersion())
    assert len(frame) == 3
    assert np.isclose(frame.loc[0, "advance_ratio"], 0.20)
    assert np.isclose(frame.loc[1, "delta_advance_ratio"], 0.15)
    assert np.isclose(frame.loc[2, "delta_decline_ratio"], -0.20)
    assert np.isclose(frame.loc[2, "seal_industry_ratio"], 7 / 20)
    assert np.isclose(frame.loc[2, "delta_positive_industry_ratio"], 0.25)
    assert np.isclose(frame.loc[2, "delta_seal_hhi"], -0.20)
    assert not any(m05.invariant_failures(frame).values())


def test_missing_prior_winner_sample_is_not_imputed_to_zero():
    frame = m05.build_recovery_dynamics(_tape(), _dispersion())
    assert pd.isna(frame.loc[0, "prior_seal_mean_return"])
    assert pd.isna(frame.loc[0, "delta_prior_seal_mean_return"])
    assert pd.isna(frame.loc[1, "delta_prior_seal_mean_return"])
    assert np.isclose(frame.loc[2, "delta_prior_seal_mean_return"], 0.05)
    assert pd.isna(frame.loc[2, "delta_prior_multi_board_mean_return"])


def test_future_input_change_cannot_change_past_rows():
    base = m05.build_recovery_dynamics(_tape(), _dispersion())
    tape = _tape()
    dispersion = _dispersion()
    tape.loc[2, "advance_count"] = 1
    tape.loc[2, "decline_count"] = 99
    dispersion.loc[2, "positive_industry_ratio"] = 0.01
    changed = m05.build_recovery_dynamics(tape, dispersion)
    pd.testing.assert_frame_equal(
        base.iloc[:2].reset_index(drop=True),
        changed.iloc[:2].reset_index(drop=True),
        check_dtype=False,
    )


def test_date_lineage_mismatch_fails_closed():
    dispersion = _dispersion().iloc[:2].copy()
    with pytest.raises(RuntimeError, match="date lineage mismatch"):
        m05.build_recovery_dynamics(_tape(), dispersion)


def test_contract_forbids_state_or_return_promotion():
    c = m05.CONTRACT
    assert c["difference_horizon_completed_sessions"] == 1
    assert c["missing_prior_winner_returns_filled_with_zero"] is False
    assert c["uses_strategy_returns"] is False
    assert c["uses_fitted_thresholds"] is False
    assert c["parameter_search"] is False
    assert c["market_state_label_authorized"] is False
    assert c["recovery_score_authorized"] is False
    assert c["w01_return_screen_authorized"] is False
    assert c["x02_change_authorized"] is False
    assert c["paper_trading_authorized"] is False
    assert c["live_trading_authorized"] is False
