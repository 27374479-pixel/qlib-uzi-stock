import pandas as pd

import v5_w08_leader_evidence as w08


def sample_panel():
    rows = [
        # fully observed accessible three-board streak, then first unsealed row
        ("A", "2026-01-05", 8.0, 400_000_000, 4.0, True, False, 1),
        ("A", "2026-01-06", 8.8, 600_000_000, 5.0, True, False, 2),
        ("A", "2026-01-07", 9.68, 900_000_000, 6.0, True, False, 3),
        ("A", "2026-01-08", 10.64, 1_200_000_000, 8.0, False, False, 0),
        # panel begins mid-streak: launch/accessibility history must remain unknown
        ("B", "2026-01-05", 20.0, 1_500_000_000, 1.0, True, False, 2),
        ("B", "2026-01-06", 22.0, 1_700_000_000, 1.5, True, True, 3),
    ]
    return pd.DataFrame(rows, columns=[
        "instrument", "date", "preclose", "amount", "turnover_rate_pct",
        "seal_up", "one_word", "board_height",
    ])


def test_complete_streak_preserves_launch_and_accessibility():
    out = w08.build_leader_evidence(sample_panel())
    a3 = out[(out.instrument == "A") & (out.board_height == 3)].iloc[0]
    assert a3["three_plus_board"]
    assert a3["streak_history_complete"]
    assert a3["streak_all_accessible_proxy"]
    assert a3["streak_launch_price"] == 8.0
    assert a3["launch_price_lt_10"]


def test_first_unsealed_after_three_plus_is_causal_proxy():
    out = w08.build_leader_evidence(sample_panel())
    row = out[(out.instrument == "A") & (out.date == pd.Timestamp("2026-01-08"))].iloc[0]
    assert row["first_unsealed_after_3plus_proxy"]
    assert row["amount_ge_1bn"]
    assert not row["accessible_board_proxy"]


def test_mid_streak_history_is_not_fabricated():
    out = w08.build_leader_evidence(sample_panel())
    b = out[out.instrument == "B"]
    assert not b["streak_history_complete"].any()
    assert b["streak_launch_price"].isna().all()
    assert b["streak_all_accessible_proxy"].isna().all()
    assert b["launch_price_lt_10"].isna().all()


def test_structural_invariants_pass():
    out = w08.build_leader_evidence(sample_panel())
    assert not any(w08.invariant_failures(out).values())


def test_future_rows_do_not_change_past_evidence():
    base = sample_panel()
    short = w08.build_leader_evidence(base[base.date <= "2026-01-07"].copy())
    changed = base.copy()
    mask = changed.date == "2026-01-08"
    changed.loc[mask, "amount"] = 9_000_000_000
    changed.loc[mask, "turnover_rate_pct"] = 99.0
    full = w08.build_leader_evidence(changed)
    cols = list(short.columns)
    pd.testing.assert_frame_equal(
        short.reset_index(drop=True),
        full[full.date <= pd.Timestamp("2026-01-07")][cols].reset_index(drop=True),
        check_dtype=False,
    )


def test_contract_keeps_leader_and_trading_closed():
    c = w08.CONTRACT
    assert c["uses_strategy_returns"] is False
    assert c["parameter_search"] is False
    assert c["leader_score_authorized"] is False
    assert c["leader_rank_authorized"] is False
    assert c["leader_label_authorized"] is False
    assert c["top_anchor_authorized"] is False
    assert c["w01_return_screen_authorized"] is False
    assert c["paper_trading_authorized"] is False
    assert c["live_trading_authorized"] is False
