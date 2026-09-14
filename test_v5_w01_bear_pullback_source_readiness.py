from copy import deepcopy
from pathlib import Path

import v5_w01_bear_pullback_source_readiness as w01


def test_literal_source_parameters_are_frozen():
    p = w01.CONTRACT["literal_source_parameters"]
    assert p["pullback_window_sessions_min"] == 3
    assert p["pullback_window_sessions_max"] == 7
    assert p["drawdown_fraction_min"] == 0.20
    assert p["drawdown_fraction_max"] == 0.25
    assert p["first_post_top_occurrence"] is True


def test_default_evidence_defers_preregistration():
    decision = w01.evaluate_readiness(w01.DEFAULT_EVIDENCE)
    assert decision["status"] == "DEFER_BEAR_PULLBACK_PREREGISTRATION"
    assert decision["ready"] is False
    assert decision["signal_preregistration_authorized"] is False
    assert decision["return_screen_authorized"] is False
    assert decision["effective_action"] == "SOURCE_EXTRACTION_ONLY"


def test_default_defer_names_bear_market_and_leader_gaps():
    decision = w01.evaluate_readiness(w01.DEFAULT_EVIDENCE)
    fields = {x["field"] for x in decision["not_ready"]}
    assert "machine_ready_bear_market_state" in fields
    assert "machine_ready_leader_identity" in fields
    assert "entry_timing_and_price" in fields
    assert "exit_or_holding_rule" in fields


def test_missing_required_field_fails_closed():
    ev = deepcopy(w01.DEFAULT_EVIDENCE)
    del ev["top_anchor_definition"]
    decision = w01.evaluate_readiness(ev)
    assert decision["ready"] is False
    assert "top_anchor_definition" in decision["missing_fields"]
    assert decision["return_screen_authorized"] is False


def test_all_machine_definitions_only_enable_separate_preregistration():
    ev = deepcopy(w01.DEFAULT_EVIDENCE)
    for field in w01.CONTRACT["required_for_signal_preregistration"]:
        ev[field] = {"ready": True, "detail": "independently grounded"}
    decision = w01.evaluate_readiness(ev)
    assert decision["status"] == "READY_FOR_SIGNAL_PREREGISTRATION_ONLY"
    assert decision["ready"] is True
    assert decision["signal_preregistration_authorized"] is True
    assert decision["return_screen_authorized"] is False
    assert decision["effective_action"] == "WRITE_SEPARATE_PREREGISTRATION"


def test_build_report_binds_source_review_and_never_authorizes_trading(tmp_path: Path):
    source = tmp_path / "source.md"
    source.write_text("source-grounded review\n", encoding="utf-8")
    report = w01.build_report(source)
    assert len(report["source_review_sha256"]) == 64
    assert report["decision"]["paper_trading_authorized"] is False
    assert report["decision"]["live_trading_authorized"] is False
    assert report["contract"]["parameter_search"] is False
