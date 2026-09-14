import pandas as pd

import v5_b03_leader_second_wave_screen as b03


def _rows(leader_height=3, market_other_height=2, gap=2):
    dates = pd.bdate_range("2024-01-02", periods=8)
    rows = []
    seal = [False] * 8
    board = [0] * 8
    peak_i = 3 if gap == 3 else 4
    seal[peak_i] = True
    board[peak_i] = leader_height
    seal[7] = True
    board[7] = 1
    for i, d in enumerate(dates):
        rows.append({"instrument": "SZ000001", "date": d, "seal_up": seal[i], "board_height": board[i]})
    for i, d in enumerate(dates):
        rows.append({"instrument": "SZ000002", "date": d, "seal_up": i == peak_i, "board_height": market_other_height if i == peak_i else 0})
    return pd.DataFrame(rows)


def test_gap2_market_leader_restart_is_selected():
    x = b03.add_b03_features(_rows(leader_height=3, market_other_height=2, gap=2))
    cand = x.loc[x["instrument"].eq("SZ000001")].iloc[-1]
    masks = b03.b03_masks(x)
    assert cand["gap_sessions"] == 2
    assert bool(cand["peak_was_market_leader"])
    assert bool(masks["selected"].loc[cand.name])


def test_gap3_restart_is_supported_by_frozen_two_three_day_window():
    x = b03.add_b03_features(_rows(leader_height=4, market_other_height=3, gap=3))
    cand = x.loc[x["instrument"].eq("SZ000001")].iloc[-1]
    assert cand["gap_sessions"] == 3
    assert bool(cand["peak_was_market_leader"])


def test_lower_height_restart_is_control_not_selected():
    x = b03.add_b03_features(_rows(leader_height=2, market_other_height=4, gap=2))
    cand = x.loc[x["instrument"].eq("SZ000001")].iloc[-1]
    masks = b03.b03_masks(x)
    assert not bool(masks["selected"].loc[cand.name])
    assert bool(masks["lower_height_control"].loc[cand.name])


def test_one_day_gap_does_not_qualify():
    frame = _rows(leader_height=3, market_other_height=2, gap=2)
    mask = frame["instrument"].eq("SZ000001")
    idx = frame.loc[mask].index[-2]
    frame.loc[idx, ["seal_up", "board_height"]] = [True, 1]
    x = b03.add_b03_features(frame)
    cand = x.loc[x["instrument"].eq("SZ000001")].iloc[-1]
    assert not bool(cand["second_wave_restart"])


def test_contract_is_frozen_and_does_not_enable_search():
    assert b03.PRIMARY_HORIZON == 2
    assert b03.CONTRACT["parameter_search"] is False
    assert "2 or 3" in b03.CONTRACT["selected"]


def test_b03_config_binds_report_and_observation_paths_to_b03():
    config = b03.screen_config()
    assert config.output == "output/v5_b03_leader_second_wave/report.json"
    assert config.observations_output == "output/v5_b03_leader_second_wave/observations.parquet"


def test_b03_qualification_uses_lower_height_control_wording():
    segment = {
        "selected": {"n": 1, "active_days": 1, "mean_return": -0.01, "mean_market_excess": -0.01},
        "paired": {"paired_days": 1, "expected_signed_difference": -0.01, "bootstrap95_expected_signed_difference": [-0.02, 0.01]},
    }
    result = b03.b03_qualification(segment, segment)
    assert any("lower-height-control" in reason for reason in result["reasons"])
    assert all("volume-control" not in reason for reason in result["reasons"])
