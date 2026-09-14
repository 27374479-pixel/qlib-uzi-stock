import pandas as pd

import v5_b01_leader_disagreement_screen as b01


def _base_frame(event_amount=2_000_000_000.0, prior_peak=800_000_000.0, prior_one_word=False):
    dates = pd.bdate_range("2024-01-02", periods=15)
    amounts = [500_000_000.0] * 15
    amounts[8] = prior_peak
    amounts[14] = event_amount
    board = [0] * 15
    seals = [False] * 15
    one_word = [False] * 15
    board[11:14] = [1, 2, 3]
    seals[11:14] = [True, True, True]
    if prior_one_word:
        one_word[12] = True
    return pd.DataFrame(
        {
            "instrument": ["SZ000001"] * 15,
            "date": dates,
            "amount": amounts,
            "board_height": board,
            "seal_up": seals,
            "one_word": one_word,
        }
    )


def test_book_pattern_selects_first_post_three_board_disagreement():
    frame = b01.add_b01_features(_base_frame())
    masks = b01.b01_masks(frame)
    assert bool(frame.iloc[-1]["first_disagreement"])
    assert bool(masks["selected"].iloc[-1])
    assert not bool(masks["volume_control"].iloc[-1])


def test_primary_volume_control_holds_other_book_conditions_fixed():
    frame = b01.add_b01_features(
        _base_frame(event_amount=1_500_000_000.0, prior_peak=2_000_000_000.0)
    )
    masks = b01.b01_masks(frame)
    assert not bool(masks["selected"].iloc[-1])
    assert bool(masks["volume_control"].iloc[-1])


def test_one_word_prior_board_moves_event_to_accessibility_control():
    frame = b01.add_b01_features(
        _base_frame(event_amount=2_500_000_000.0, prior_peak=2_000_000_000.0, prior_one_word=True)
    )
    masks = b01.b01_masks(frame)
    assert not bool(masks["selected"].iloc[-1])
    assert bool(masks["accessibility_control"].iloc[-1])


def test_sub_one_billion_new_high_is_size_diagnostic_control():
    frame = b01.add_b01_features(
        _base_frame(event_amount=900_000_000.0, prior_peak=800_000_000.0)
    )
    masks = b01.b01_masks(frame)
    assert not bool(masks["selected"].iloc[-1])
    assert bool(masks["turnover_size_control"].iloc[-1])


def test_future_amount_change_cannot_change_current_b01_signal():
    frame = pd.concat(
        [_base_frame(), pd.DataFrame({
            "instrument": ["SZ000001"],
            "date": [pd.Timestamp("2024-01-23")],
            "amount": [100_000_000.0],
            "board_height": [0],
            "seal_up": [False],
            "one_word": [False],
        })],
        ignore_index=True,
    )
    first = b01.add_b01_features(frame)
    signal_before = bool(b01.b01_masks(first)["selected"].iloc[14])
    changed = frame.copy()
    changed.loc[15, "amount"] = 99_000_000_000.0
    second = b01.add_b01_features(changed)
    signal_after = bool(b01.b01_masks(second)["selected"].iloc[14])
    assert signal_before is True
    assert signal_after is True


def _primary_segment(n=40, days=25, paired_days=20, mean_return=.01, excess=.004, diff=.003, lower=.001):
    return {
        "selected": {
            "n": n,
            "active_days": days,
            "mean_return": mean_return,
            "mean_market_excess": excess,
        },
        "paired": {
            "paired_days": paired_days,
            "expected_signed_difference": diff,
            "bootstrap95_expected_signed_difference": [lower, .01],
        },
    }


def test_qualification_requires_both_historical_segments():
    result = b01.qualification_from_primary(_primary_segment(), _primary_segment())
    assert result["status"] == "QUALIFIED_FOR_MINUTE_REPLAY"
    assert result["qualified_for_minute_replay"] is True
    assert result["portfolio_combination_authorized"] is False


def test_insufficient_sample_is_not_mislabeled_as_rejection_or_pass():
    result = b01.qualification_from_primary(_primary_segment(n=29), _primary_segment())
    assert result["status"] == "INSUFFICIENT"
    assert result["qualified_for_minute_replay"] is False


def test_nonpositive_bootstrap_lower_bound_rejects_when_sample_is_sufficient():
    result = b01.qualification_from_primary(_primary_segment(lower=0.0), _primary_segment())
    assert result["status"] == "REJECTED"
    assert result["qualified_for_minute_replay"] is False
    assert any("bootstrap" in reason for reason in result["reasons"])


def test_primary_horizon_and_book_literal_threshold_are_frozen():
    assert b01.PRIMARY_HORIZON == 2
    assert b01.CONTRACT["round_trip_cost"] == 0.0036
    assert "1bn_CNY" in b01.CONTRACT["selected"]
