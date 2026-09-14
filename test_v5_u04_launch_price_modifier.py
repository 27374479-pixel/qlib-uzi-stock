import pandas as pd

import v5_u04_launch_price_modifier as u04


def _frame():
    dates = list(pd.bdate_range("2024-01-02", periods=8))
    return pd.DataFrame(
        {
            "instrument": ["A"] * 4 + ["B"] * 4,
            "date": dates[:4] + dates[:4],
            "seal_up": [False, True, True, True, False, True, True, True],
            "board_height": [0, 1, 2, 3, 0, 1, 2, 3],
            "one_word": [False] * 8,
            # first-board row is row 1 for each instrument, so its preclose is
            # the frozen launch-reference price used at row 3.
            "preclose": [8.0, 8.5, 9.35, 10.28, 12.0, 12.5, 13.75, 15.12],
        }
    )


def test_launch_reference_price_is_preclose_on_first_board_row():
    x = u04.add_u04_features(_frame())
    a = x.loc[(x["instrument"] == "A") & x["board_height"].eq(3)].iloc[0]
    b = x.loc[(x["instrument"] == "B") & x["board_height"].eq(3)].iloc[0]
    assert a["launch_reference_price"] == 8.5
    assert b["launch_reference_price"] == 12.5
    assert bool(a["low_launch_price"]) is True
    assert bool(b["low_launch_price"]) is False


def test_exact_10_cny_boundary_belongs_to_control():
    frame = _frame()
    frame.loc[(frame["instrument"] == "A") & frame["board_height"].eq(1), "preclose"] = 10.0
    x = u04.add_u04_features(frame)
    masks = u04.u04_masks(x)
    row = x.index[(x["instrument"] == "A") & x["board_height"].eq(3)][0]
    assert bool(masks["selected_lt10"].loc[row]) is False
    assert bool(masks["control_gte10"].loc[row]) is True


def test_one_word_anywhere_in_three_board_sequence_excludes_event():
    frame = _frame()
    frame.loc[(frame["instrument"] == "A") & frame["board_height"].eq(2), "one_word"] = True
    x = u04.add_u04_features(frame)
    masks = u04.u04_masks(x)
    row = x.index[(x["instrument"] == "A") & x["board_height"].eq(3)][0]
    assert bool(x.loc[row, "three_board_start"]) is True
    assert bool(x.loc[row, "three_board_accessible"]) is False
    assert bool(masks["selected_lt10"].loc[row]) is False
    assert bool(masks["control_gte10"].loc[row]) is False


def test_invalid_nominal_launch_price_enters_neither_cohort():
    frame = _frame()
    frame.loc[(frame["instrument"] == "A") & frame["board_height"].eq(1), "preclose"] = 0.0
    x = u04.add_u04_features(frame)
    masks = u04.u04_masks(x)
    row = x.index[(x["instrument"] == "A") & x["board_height"].eq(3)][0]
    assert bool(masks["selected_lt10"].loc[row]) is False
    assert bool(masks["control_gte10"].loc[row]) is False


def _primary(n=40, days=25, control_n=45, control_days=26, paired=18, diff=0.01, lower=0.002):
    return {
        "selected": {"n": n, "active_days": days, "mean_return": -0.01},
        "control": {"n": control_n, "active_days": control_days, "mean_return": -0.02},
        "paired": {
            "paired_days": paired,
            "expected_signed_difference": diff,
            "bootstrap95_expected_signed_difference": [lower, 0.02],
        },
    }


def test_modifier_can_qualify_relatively_even_if_absolute_returns_are_negative():
    result = u04.qualification_from_primary(_primary(), _primary())
    assert result["status"] == "QUALIFIED_AS_RELATIVE_MODIFIER_ONLY"
    assert result["qualified_as_relative_modifier_only"] is True
    assert result["standalone_signal_authorized"] is False
    assert result["paper_trading_authorized"] is False
    assert result["live_trading_authorized"] is False


def test_sample_shortfall_is_insufficient():
    result = u04.qualification_from_primary(_primary(paired=14), _primary())
    assert result["status"] == "INSUFFICIENT"
    assert result["qualified_as_relative_modifier_only"] is False


def test_nonpositive_relative_difference_is_rejected_when_coverage_is_sufficient():
    result = u04.qualification_from_primary(_primary(diff=0.0), _primary())
    assert result["status"] == "REJECTED"
    assert any("difference" in reason for reason in result["reasons"])


def test_bootstrap_lower_bound_must_be_strictly_positive():
    result = u04.qualification_from_primary(_primary(lower=0.0), _primary())
    assert result["status"] == "REJECTED"
    assert any("bootstrap" in reason for reason in result["reasons"])


def test_contract_freezes_exact_source_threshold_and_authorization_boundary():
    assert u04.PRICE_THRESHOLD == 10.0
    assert u04.CONTRACT["selected"] == "launch_reference_price < 10.00 CNY"
    assert u04.PRIMARY_HORIZON == 2
    assert u04.ROUND_TRIP_COST == 0.0036
    assert u04.CONTRACT["parameter_search"] is False
    assert u04.CONTRACT["standalone_signal_authorized"] is False
    assert u04.CONTRACT["x02_retuning_authorized"] is False
    assert u04.CONTRACT["portfolio_combination_authorized"] is False
