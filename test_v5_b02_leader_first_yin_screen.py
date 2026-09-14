import pandas as pd

import v5_b02_leader_first_yin_screen as b02


def _two_stock_frame():
    dates = pd.bdate_range("2024-01-02", periods=5)
    rows = []
    for instrument, prior_height in (("SZ000001", 3), ("SZ000002", 2)):
        heights = [0, 1, max(1, prior_height - 1), prior_height, 0]
        seals = [False, True, True, True, False]
        returns = [0.01, 0.10, 0.10, 0.10, -0.03]
        for date, height, seal, ret in zip(dates, heights, seals, returns):
            rows.append(
                {
                    "instrument": instrument,
                    "date": date,
                    "board_height": height,
                    "seal_up": seal,
                    "one_word": False,
                    "ret1": ret,
                }
            )
    return pd.DataFrame(rows)


def _row(frame, instrument, date):
    return frame.loc[(frame["instrument"] == instrument) & (frame["date"] == date)].iloc[0]


def test_market_max_first_yin_selects_leader_and_lower_height_control():
    raw = _two_stock_frame()
    frame = b02.add_b02_features(raw)
    masks = b02.b02_masks(frame)
    signal_date = raw["date"].max()

    leader_idx = frame.index[(frame["instrument"] == "SZ000001") & (frame["date"] == signal_date)][0]
    control_idx = frame.index[(frame["instrument"] == "SZ000002") & (frame["date"] == signal_date)][0]

    assert bool(frame.loc[leader_idx, "first_yin_after_streak"])
    assert frame.loc[leader_idx, "prev_board_height"] == 3
    assert frame.loc[leader_idx, "prev_market_max_board_height"] == 3
    assert bool(masks["selected"].loc[leader_idx])
    assert not bool(masks["lower_height_control"].loc[leader_idx])

    assert frame.loc[control_idx, "prev_board_height"] == 2
    assert frame.loc[control_idx, "prev_market_max_board_height"] == 3
    assert not bool(masks["selected"].loc[control_idx])
    assert bool(masks["lower_height_control"].loc[control_idx])


def test_first_yin_requires_current_negative_and_nonsealed():
    raw = _two_stock_frame()
    signal_date = raw["date"].max()
    raw.loc[(raw["instrument"] == "SZ000001") & (raw["date"] == signal_date), "ret1"] = 0.01
    frame = b02.add_b02_features(raw)
    leader = _row(frame, "SZ000001", signal_date)
    assert not bool(leader["first_yin_after_streak"])

    raw = _two_stock_frame()
    raw.loc[(raw["instrument"] == "SZ000001") & (raw["date"] == signal_date), "seal_up"] = True
    raw.loc[(raw["instrument"] == "SZ000001") & (raw["date"] == signal_date), "board_height"] = 4
    frame = b02.add_b02_features(raw)
    leader = _row(frame, "SZ000001", signal_date)
    assert not bool(leader["first_yin_after_streak"])


def test_tied_market_maxima_are_both_leaders_without_arbitrary_tiebreak():
    raw = _two_stock_frame()
    prior_date = sorted(raw["date"].unique())[-2]
    raw.loc[(raw["instrument"] == "SZ000002") & (raw["date"] == prior_date), "board_height"] = 3
    frame = b02.add_b02_features(raw)
    masks = b02.b02_masks(frame)
    signal_date = raw["date"].max()
    rows = frame.loc[frame["date"] == signal_date]
    assert masks["selected"].loc[rows.index].sum() == 2
    assert masks["lower_height_control"].loc[rows.index].sum() == 0


def test_amount_turnover_and_one_word_history_do_not_define_b02_eligibility():
    raw = _two_stock_frame()
    raw["amount"] = 1.0
    raw["turnover_rate_pct"] = 99.0
    prior_date = sorted(raw["date"].unique())[-2]
    raw.loc[(raw["instrument"] == "SZ000001") & (raw["date"] == prior_date), "one_word"] = True
    frame = b02.add_b02_features(raw)
    masks = b02.b02_masks(frame)
    signal_date = raw["date"].max()
    leader_idx = frame.index[(frame["instrument"] == "SZ000001") & (frame["date"] == signal_date)][0]
    assert bool(masks["selected"].loc[leader_idx])


def test_future_row_change_cannot_change_current_b02_signal():
    raw = _two_stock_frame()
    signal_date = raw["date"].max()
    future_date = signal_date + pd.offsets.BDay(1)
    extra = pd.DataFrame(
        [
            {"instrument": "SZ000001", "date": future_date, "board_height": 0, "seal_up": False, "one_word": False, "ret1": 0.01},
            {"instrument": "SZ000002", "date": future_date, "board_height": 0, "seal_up": False, "one_word": False, "ret1": 0.01},
        ]
    )
    first_raw = pd.concat([raw, extra], ignore_index=True)
    first = b02.add_b02_features(first_raw)
    first_masks = b02.b02_masks(first)
    idx = first.index[(first["instrument"] == "SZ000001") & (first["date"] == signal_date)][0]
    before = bool(first_masks["selected"].loc[idx])

    changed = first_raw.copy()
    changed.loc[changed["date"] == future_date, "board_height"] = 12
    second = b02.add_b02_features(changed)
    second_masks = b02.b02_masks(second)
    idx2 = second.index[(second["instrument"] == "SZ000001") & (second["date"] == signal_date)][0]
    after = bool(second_masks["selected"].loc[idx2])
    assert before is True
    assert after is True


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


def test_qualification_requires_both_segments_and_fixed_relative_evidence():
    result = b02.qualification_from_primary(_primary_segment(), _primary_segment())
    assert result["status"] == "QUALIFIED_FOR_MINUTE_REPLAY"
    assert result["qualified_for_minute_replay"] is True
    assert result["portfolio_combination_authorized"] is False
    assert result["live_trading_authorized"] is False


def test_insufficient_coverage_is_not_mislabeled_as_pass():
    result = b02.qualification_from_primary(_primary_segment(paired_days=14), _primary_segment())
    assert result["status"] == "INSUFFICIENT"
    assert result["qualified_for_minute_replay"] is False


def test_nonpositive_primary_return_rejects_when_coverage_is_sufficient():
    result = b02.qualification_from_primary(_primary_segment(mean_return=0.0), _primary_segment())
    assert result["status"] == "REJECTED"
    assert any("mean net return" in reason for reason in result["reasons"])


def test_b02_contract_is_nonparametric_and_frozen():
    assert b02.PRIMARY_HORIZON == 2
    assert b02.CONTRACT["round_trip_cost"] == 0.0036
    assert b02.CONTRACT["parameter_search"] is False
    assert "equals the point-in-time" in b02.CONTRACT["leader_proxy"]
    assert "amount" in b02.CONTRACT["excluded_from_eligibility"]
