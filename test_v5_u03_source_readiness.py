import copy

import v5_u03_source_readiness as u03


def test_default_source_is_deferred_before_any_return_screen():
    decision = u03.evaluate(u03.DEFAULT_EVIDENCE)
    assert decision["status"] == "DEFER_SIGNAL_PREREGISTRATION"
    assert decision["ready"] is False
    assert decision["return_screen_authorized"] is False
    assert decision["paper_trading_authorized"] is False
    assert decision["live_trading_authorized"] is False
    blocked = {item["field"] for item in decision["not_ready"]}
    assert "source_layout_integrity" in blocked
    assert "target_security_definition" in blocked
    assert "entry_timing_definition" in blocked
    assert "economic_direction_and_control_definition" in blocked


def test_explicit_two_three_day_context_does_not_make_signal_ready():
    assert u03.DEFAULT_EVIDENCE["leader_ebb_rough_window"]["ready"] is True
    assert "leader_ebb_rough_window" not in u03.REQUIRED_FOR_SIGNAL_PREREGISTRATION
    assert u03.evaluate(u03.DEFAULT_EVIDENCE)["ready"] is False


def test_missing_required_field_is_reported():
    evidence = copy.deepcopy(u03.DEFAULT_EVIDENCE)
    evidence.pop("candidate_ranking_rule")
    decision = u03.evaluate(evidence)
    assert decision["ready"] is False
    assert decision["missing_fields"] == ["candidate_ranking_rule"]


def test_readiness_requires_every_predeclared_source_field():
    evidence = copy.deepcopy(u03.DEFAULT_EVIDENCE)
    for name in u03.REQUIRED_FOR_SIGNAL_PREREGISTRATION:
        evidence[name]["ready"] = True
    decision = u03.evaluate(evidence)
    assert decision["status"] == "READY_FOR_SIGNAL_PREREGISTRATION"
    assert decision["ready"] is True
    # Source readiness alone still never authorizes a return screen or trading.
    assert decision["return_screen_authorized"] is False
    assert decision["paper_trading_authorized"] is False
    assert decision["live_trading_authorized"] is False


def test_contract_cannot_authorize_outcome_search_or_trading():
    assert u03.CONTRACT["parameter_search"] is False
    assert u03.CONTRACT["return_screen_authorized"] is False
    assert u03.CONTRACT["signal_preregistration_authorized"] is False
    assert u03.CONTRACT["paper_trading_authorized"] is False
    assert u03.CONTRACT["live_trading_authorized"] is False
