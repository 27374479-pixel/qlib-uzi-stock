from __future__ import annotations

from copy import deepcopy

import v5_t02_trend_exit_source_readiness as t02


def test_literal_source_parameters_are_frozen() -> None:
    assert t02.CONTRACT["literal_source_parameters"] == {
        "no_new_high_window_sessions": 3,
        "moving_average_period_sessions": 10,
    }
    assert t02.CONTRACT["parameter_search"] is False


def test_current_source_review_defers_preregistration() -> None:
    report = t02.build_report()
    decision = report["decision"]
    assert decision["status"] == "DEFER_TREND_EXIT_PREREGISTRATION"
    assert decision["ready"] is False
    assert decision["exit_preregistration_authorized"] is False
    assert decision["return_screen_authorized"] is False
    assert decision["effective_action"] == "SOURCE_EXTRACTION_ONLY"


def test_missing_prerequisite_state_is_fail_closed() -> None:
    report = t02.build_report()
    not_ready = {item["field"] for item in report["decision"]["not_ready"]}
    assert "machine_ready_trend_state" in not_ready
    assert "three_day_anchor_definition" in not_ready
    assert "ma10_break_price_definition" in not_ready


def test_current_decision_cannot_authorize_trading() -> None:
    decision = t02.build_report()["decision"]
    assert decision["x02_change_authorized"] is False
    assert decision["portfolio_combination_authorized"] is False
    assert decision["paper_trading_authorized"] is False
    assert decision["live_trading_authorized"] is False


def test_ready_fields_would_only_authorize_preregistration(monkeypatch) -> None:
    evidence = deepcopy(t02.EVIDENCE)
    for key in t02.CONTRACT["required_for_exit_preregistration"]:
        evidence[key]["ready"] = True

    monkeypatch.setattr(t02, "EVIDENCE", evidence)
    report = t02.build_report()
    decision = report["decision"]

    assert decision["status"] == "READY_FOR_TREND_EXIT_PREREGISTRATION"
    assert decision["ready"] is True
    assert decision["exit_preregistration_authorized"] is True
    # Source readiness never directly authorizes a historical screen or trading.
    assert decision["return_screen_authorized"] is False
    assert decision["paper_trading_authorized"] is False
    assert decision["live_trading_authorized"] is False
