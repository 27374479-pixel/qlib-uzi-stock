import numpy as np
import pandas as pd

import v5_m04_leadership_dispersion as mod


def _panel():
    rows = [
        ("A", "2026-01-05", "I1", 0.05, True, True, 1),
        ("B", "2026-01-05", "I1", -0.01, False, False, 0),
        ("C", "2026-01-05", "I2", 0.02, True, True, 1),
        ("D", "2026-01-05", "I3", -0.02, False, False, 0),
        ("A", "2026-01-06", "I1", 0.03, False, True, 2),
        ("B", "2026-01-06", "I1", 0.01, False, False, 0),
        ("C", "2026-01-06", "I2", -0.02, False, False, 0),
        ("D", "2026-01-06", "I3", 0.01, True, True, 1),
    ]
    return pd.DataFrame(rows, columns=["instrument","date","industry_code","ret1","first_board","seal_up","board_height"])


def test_dispersion_accounting():
    frame = mod.build_dispersion(_panel())
    assert len(frame) == 2
    d1 = frame.iloc[0]
    assert d1["known_industry_n"] == 3
    assert d1["positive_industry_n"] == 2
    assert d1["seal_industry_n"] == 2
    assert d1["seal_total"] == 2
    assert np.isclose(d1["seal_top1_share"], 0.5)
    assert np.isclose(d1["seal_hhi"], 0.5)
    assert not any(mod.invariant_failures(frame).values())


def test_future_rows_do_not_change_past():
    panel = _panel()
    first = mod.build_dispersion(panel[pd.to_datetime(panel["date"]) == pd.Timestamp("2026-01-05")])
    changed = panel.copy()
    future = pd.to_datetime(changed["date"]) == pd.Timestamp("2026-01-06")
    changed.loc[future, "ret1"] = [0.9, -0.9, 0.8, -0.8]
    changed.loc[future, "seal_up"] = [True, True, True, True]
    full = mod.build_dispersion(changed)
    pd.testing.assert_frame_equal(first.reset_index(drop=True), full.iloc[[0]].reset_index(drop=True), check_dtype=False)


def test_zero_event_distribution_is_zero():
    panel = _panel()
    panel["seal_up"] = False
    panel["first_board"] = False
    panel["board_height"] = 0
    frame = mod.build_dispersion(panel)
    assert (frame["seal_top1_share"] == 0).all()
    assert (frame["seal_hhi"] == 0).all()
    assert (frame["first_board_top1_share"] == 0).all()
    assert (frame["multi_board_hhi"] == 0).all()


def test_contract_forbids_state_promotion():
    c = mod.CONTRACT
    assert c["uses_strategy_returns"] is False
    assert c["parameter_search"] is False
    assert c["market_state_label_authorized"] is False
    assert c["w01_return_screen_authorized"] is False
    assert c["live_trading_authorized"] is False
