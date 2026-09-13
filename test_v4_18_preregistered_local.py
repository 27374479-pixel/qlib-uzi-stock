"""Causal invariants for the integrated formal runner, without real returns."""
import json
from pathlib import Path

import pandas as pd
import pytest

import v4_18_run_h04_h05_preregistered as runner

ROOT = Path(__file__).resolve().parent


def test_red_gate_blocks_control_plane(tmp_path):
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps({"scientific_status": "BLOCKED"}), encoding="utf-8")
    with pytest.raises(SystemExit, match="locked before cluster/X02/market I/O"):
        runner.validate_control_plane(
            gate, ROOT / "v4_18_h04_h05_prereg_v1.json",
            ROOT / "v4_18_h04_h05_runner_contract_v1.json",
        )


def test_future_members_and_events_cannot_change_past():
    days = pd.bdate_range("2026-01-02", periods=80).strftime("%Y-%m-%d").tolist()
    index = dict(zip(days, range(len(days))))
    candidates = pd.DataFrame([dict(trade_date=days[65], signal_date=days[64], instrument="SH600001")])
    members = pd.DataFrame([
        dict(cluster_id="a", instrument="SH600001", member_first_session_index=63, cluster_first_session_index=63),
        dict(cluster_id="a", instrument="SZ000002", member_first_session_index=64, cluster_first_session_index=63),
    ])
    events = pd.DataFrame([dict(cluster_id="a", session_index=64)])
    original = runner.attach_event_context(candidates, events, members, index, days[0])
    future_members = pd.concat([members, pd.DataFrame([
        dict(cluster_id="a", instrument="SZ000003", member_first_session_index=70, cluster_first_session_index=63),
        dict(cluster_id="b", instrument="SH600001", member_first_session_index=71, cluster_first_session_index=71),
    ])], ignore_index=True)
    future_events = pd.concat([events, pd.DataFrame([
        dict(cluster_id="a", session_index=70), dict(cluster_id="b", session_index=71),
    ])], ignore_index=True)
    extended = runner.attach_event_context(candidates, future_events, future_members, index, days[0])
    pd.testing.assert_frame_equal(original, extended)
    shuffled = runner.attach_event_context(
        candidates, future_events.sample(frac=1, random_state=7),
        future_members.sample(frac=1, random_state=9), index, days[0],
    )
    pd.testing.assert_frame_equal(original, shuffled)
    assert original.iloc[0].known_stock_count == 2


def test_h05_missing_member_does_not_inflate_breadth():
    context = pd.DataFrame([dict(
        trade_date="2026-05-05", signal_date="2026-05-04", instrument="SH600001",
        _known_members=["SH600001", "SZ000002"], known_stock_count=2,
        burn_in_complete=True, h04_age_bin="EARLY", group_formed=True,
    )])
    missing = runner.add_h05_context(context, {("SH600001", "2026-05-04"): 0.04}).iloc[0]
    assert missing.positive_ratio_t1 == 0.5
    assert not missing.primary_confluence
    complete = runner.add_h05_context(context, {
        ("SH600001", "2026-05-04"): 0.04, ("SZ000002", "2026-05-04"): 0.01,
        ("SZ000002", "2026-05-05"): -0.50,
    }).iloc[0]
    assert complete.positive_ratio_t1 == 1.0
    assert complete.primary_confluence
