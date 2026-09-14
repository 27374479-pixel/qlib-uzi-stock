import pandas as pd
import pytest

import v5_l01_leader_stage_transition_audit as l01


def _frame():
    dates = pd.bdate_range("2024-01-02", periods=16)
    rows = []

    # A: clean launch -> confirmation -> fermentation -> acceleration -> disagreement -> counter-wrap.
    a = [
        (True, 1),
        (True, 2),
        (True, 3),
        (True, 4),
        (False, 0),
        (True, 1),
    ]
    for i, (seal, board) in enumerate(a):
        rows.append({"instrument": "SZ000001", "date": dates[i], "seal_up": seal, "board_height": board})

    # B: high board -> two non-sealed sessions -> reseal. Recovery precedence must label dragon-return,
    # not ordinary launch even when board_height resets to 1.
    b = [
        (True, 3),
        (False, 0),
        (False, 0),
        (True, 1),
    ]
    for i, (seal, board) in enumerate(b):
        rows.append({"instrument": "SZ000002", "date": dates[i], "seal_up": seal, "board_height": board})

    # C: high board -> three non-sealed sessions -> reseal.
    c = [
        (True, 4),
        (False, 0),
        (False, 0),
        (False, 0),
        (True, 1),
    ]
    for i, (seal, board) in enumerate(c):
        rows.append({"instrument": "SZ000003", "date": dates[i], "seal_up": seal, "board_height": board})

    return pd.DataFrame(rows)


def test_frozen_stage_sequence_proxy_and_recovery_precedence():
    x = l01.annotate_stages(_frame())
    a = x.loc[x["instrument"].eq("SZ000001"), "stage_proxy"].tolist()
    assert a == [
        "launch",
        "confirmation",
        "fermentation",
        "acceleration",
        "disagreement",
        "counter_wrap",
    ]

    b = x.loc[x["instrument"].eq("SZ000002")].iloc[-1]
    assert bool(b["raw_launch"])
    assert bool(b["raw_dragon_return"])
    assert b["stage_proxy"] == "dragon_return"
    assert b["dragon_return_gap_sessions"] == 2

    c = x.loc[x["instrument"].eq("SZ000003")].iloc[-1]
    assert c["stage_proxy"] == "dragon_return"
    assert c["dragon_return_gap_sessions"] == 3


def test_counter_wrap_is_one_interruption_not_two_or_three():
    x = l01.annotate_stages(_frame())
    row = x.loc[x["instrument"].eq("SZ000001")].iloc[-1]
    assert bool(row["raw_counter_wrap"])
    assert not bool(row["raw_dragon_return"])
    assert row["stage_proxy"] == "counter_wrap"


def test_structural_invariants_are_clean_for_synthetic_sequence():
    x = l01.annotate_stages(_frame())
    failures = l01.invariant_failures(x)
    assert all(v == 0 for v in failures.values())


def test_precursor_consistency_reports_expected_links():
    x = l01.annotate_stages(_frame())
    p = l01.precursor_consistency(x)
    assert p["confirmation_immediately_after_launch"]["rate"] == 1.0
    assert p["fermentation_immediately_after_confirmation"]["rate"] == 1.0
    assert p["first_acceleration_immediately_after_fermentation"]["rate"] == 1.0
    assert p["counter_wrap_immediately_after_disagreement"]["rate"] == 1.0
    assert p["dragon_return_has_frozen_2_or_3_session_gap"]["rate"] == 1.0


def test_transition_tables_do_not_use_returns():
    x = l01.annotate_stages(_frame())
    transitions = l01._transition_records(x)
    assert transitions["immediate_next_row"]
    assert transitions["next_labelled_stage"]
    assert "return_2d" not in x.columns


def test_duplicate_instrument_date_is_rejected():
    frame = _frame()
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(RuntimeError, match="duplicate instrument/date"):
        l01.annotate_stages(frame)


def test_contract_forbids_alpha_and_trading_promotion():
    assert l01.CONTRACT["uses_forward_returns"] is False
    assert l01.CONTRACT["parameter_search"] is False
    assert l01.CONTRACT["alpha_evaluation_authorized"] is False
    assert l01.CONTRACT["trading_signal_authorized"] is False
    assert l01.CONTRACT["paper_trading_authorized"] is False
    assert l01.CONTRACT["live_trading_authorized"] is False
    assert l01.CONTRACT["label_precedence"][:2] == ["dragon_return", "counter_wrap"]
