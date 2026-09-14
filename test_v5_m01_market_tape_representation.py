import numpy as np
import pandas as pd

import v5_m01_market_tape_representation as m01


def _frame() -> pd.DataFrame:
    rows = [
        # day 1
        ("A", "2026-01-05", 0.10, True, True, False, False, 1),
        ("B", "2026-01-05", -0.10, False, False, False, True, 0),
        ("C", "2026-01-05", 0.00, True, False, True, False, 0),
        # day 2: A becomes 2-board; B advances; C declines
        ("A", "2026-01-06", 0.10, True, True, False, False, 2),
        ("B", "2026-01-06", 0.02, False, False, False, False, 0),
        ("C", "2026-01-06", -0.03, False, False, False, False, 0),
        # day 3: prior two-board A loses, B seals first board, C flat
        ("A", "2026-01-07", -0.04, False, False, False, False, 0),
        ("B", "2026-01-07", 0.10, True, True, False, False, 1),
        ("C", "2026-01-07", 0.00, False, False, False, False, 0),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "instrument",
            "date",
            "ret1",
            "touch_up",
            "seal_up",
            "broken_up",
            "limit_down_close",
            "board_height",
        ],
    )


def test_market_tape_accounting_and_book_named_dimensions():
    tape = m01.build_market_tape(_frame())
    assert list(tape.columns) == ["date", *m01.TAPE_COLUMNS]
    assert len(tape) == 3

    d1 = tape.iloc[0]
    assert d1["universe_n"] == 3
    assert d1["advance_count"] == 1
    assert d1["decline_count"] == 1
    assert d1["flat_count"] == 1
    assert d1["touch_count"] == 2
    assert d1["seal_count"] == 1
    assert d1["broken_count"] == 1
    assert d1["limit_down_count"] == 1
    assert d1["max_board_height"] == 1
    assert d1["multi_board_count"] == 0
    assert d1["prior_seal_sample_n"] == 0

    d2 = tape.iloc[1]
    assert d2["max_board_height"] == 2
    assert d2["multi_board_count"] == 1
    assert d2["prior_seal_sample_n"] == 1
    assert np.isclose(d2["prior_seal_mean_return"], 0.10)

    d3 = tape.iloc[2]
    assert d3["prior_seal_sample_n"] == 1
    assert np.isclose(d3["prior_seal_mean_return"], -0.04)
    assert d3["prior_multi_board_sample_n"] == 1
    assert np.isclose(d3["prior_multi_board_mean_return"], -0.04)
    assert not any(m01.invariant_failures(tape).values())


def test_future_rows_cannot_change_past_market_tape():
    base = _frame()
    first_two = m01.build_market_tape(base.loc[pd.to_datetime(base["date"]) <= pd.Timestamp("2026-01-06")])

    changed = base.copy()
    future = pd.to_datetime(changed["date"]).eq(pd.Timestamp("2026-01-07"))
    changed.loc[future, "ret1"] = [0.77, -0.66, 0.55]
    changed.loc[future, "touch_up"] = [True, True, True]
    changed.loc[future, "seal_up"] = [True, False, True]
    changed.loc[future, "broken_up"] = [False, True, False]
    changed.loc[future, "board_height"] = [7, 0, 3]
    full = m01.build_market_tape(changed)

    cols = ["date", *m01.TAPE_COLUMNS]
    pd.testing.assert_frame_equal(
        first_two[cols].reset_index(drop=True),
        full.loc[full["date"] <= pd.Timestamp("2026-01-06"), cols].reset_index(drop=True),
        check_dtype=False,
    )


def test_duplicate_instrument_date_is_rejected():
    frame = _frame()
    dup = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    try:
        m01.build_market_tape(dup)
    except RuntimeError as exc:
        assert "duplicate instrument/date" in str(exc)
    else:
        raise AssertionError("duplicate row should fail")


def test_invariant_checker_detects_broken_accounting():
    tape = m01.build_market_tape(_frame())
    tape.loc[0, "broken_count"] = 0
    failures = m01.invariant_failures(tape)
    assert failures["broken_accounting"] == 1


def test_contract_forbids_regime_and_trading_promotion():
    c = m01.CONTRACT
    assert c["uses_forward_returns"] is False
    assert c["uses_rolling_thresholds"] is False
    assert c["parameter_search"] is False
    assert c["regime_labels_authorized"] is False
    assert c["alpha_evaluation_authorized"] is False
    assert c["w01_return_screen_authorized"] is False
    assert c["x02_change_authorized"] is False
    assert c["portfolio_combination_authorized"] is False
    assert c["paper_trading_authorized"] is False
    assert c["live_trading_authorized"] is False


def test_no_regime_label_columns_are_emitted():
    tape = m01.build_market_tape(_frame())
    forbidden = {"weak_market", "bear", "bull", "regime", "opportunity_present"}
    assert forbidden.isdisjoint(set(tape.columns))
