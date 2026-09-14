import pandas as pd

import v5_w09_leader_ambiguity as w09


def _evidence():
    return pd.DataFrame([
        {"date":"2026-01-05","board_height":3,"three_plus_board":True,"streak_history_complete":True,"streak_all_accessible_proxy":True,"launch_price_lt_10":True,"first_unsealed_after_3plus_proxy":False},
        {"date":"2026-01-05","board_height":3,"three_plus_board":True,"streak_history_complete":True,"streak_all_accessible_proxy":False,"launch_price_lt_10":False,"first_unsealed_after_3plus_proxy":False},
        {"date":"2026-01-05","board_height":1,"three_plus_board":False,"streak_history_complete":True,"streak_all_accessible_proxy":True,"launch_price_lt_10":True,"first_unsealed_after_3plus_proxy":False},
        {"date":"2026-01-06","board_height":0,"three_plus_board":False,"streak_history_complete":False,"streak_all_accessible_proxy":pd.NA,"launch_price_lt_10":pd.NA,"first_unsealed_after_3plus_proxy":True},
    ])


def test_candidate_multiplicity_is_descriptive_only():
    out=w09.build_leader_ambiguity(_evidence(), pd.to_datetime(["2026-01-05","2026-01-06","2026-01-07"]))
    d1=out.iloc[0]
    assert d1["sealed_evidence_n"]==3
    assert d1["max_board_height"]==3
    assert d1["max_board_candidate_n"]==2
    assert d1["three_plus_candidate_n"]==2
    assert d1["complete_three_plus_candidate_n"]==2
    assert d1["accessible_three_plus_candidate_n"]==1
    assert d1["launch_lt10_three_plus_known_n"]==2
    assert d1["launch_lt10_three_plus_true_n"]==1
    assert d1["max_board_tie"]
    assert d1["three_plus_multiplicity"]
    assert out.iloc[1]["first_unsealed_after_3plus_n"]==1
    assert out.iloc[2]["sealed_evidence_n"]==0
    assert not any(w09.invariant_failures(out).values())


def test_future_evidence_does_not_change_past_date_rows():
    base=_evidence()
    first=w09.build_leader_ambiguity(base[base["date"]=="2026-01-05"], pd.to_datetime(["2026-01-05"]))
    changed=base.copy()
    extra=pd.DataFrame([{"date":"2026-01-07","board_height":9,"three_plus_board":True,"streak_history_complete":True,"streak_all_accessible_proxy":True,"launch_price_lt_10":True,"first_unsealed_after_3plus_proxy":False}])
    full=w09.build_leader_ambiguity(pd.concat([changed,extra],ignore_index=True), pd.to_datetime(["2026-01-05","2026-01-06","2026-01-07"]))
    pd.testing.assert_frame_equal(first.reset_index(drop=True), full.iloc[[0]].reset_index(drop=True), check_dtype=False)


def test_contract_does_not_promote_max_board_to_leader():
    c=w09.CONTRACT
    assert c["market_max_board_is_leader_definition"] is False
    assert c["leader_score_authorized"] is False
    assert c["leader_rank_authorized"] is False
    assert c["leader_label_authorized"] is False
    assert c["tie_resolution_authorized"] is False
    assert c["w01_return_screen_authorized"] is False
    assert c["x02_change_authorized"] is False
    assert c["portfolio_combination_authorized"] is False
    assert c["paper_trading_authorized"] is False
    assert c["live_trading_authorized"] is False


def test_invalid_nested_counts_are_detected():
    out=w09.build_leader_ambiguity(_evidence(), pd.to_datetime(["2026-01-05","2026-01-06"]))
    out.loc[0,"accessible_three_plus_candidate_n"]=3
    assert w09.invariant_failures(out)["accessible_exceed_complete"]==1
