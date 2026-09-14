import copy

import v5_w02_leader_top_source_readiness as w02


def test_current_source_evidence_defers_w01_event_preregistration():
    decision = w02.evaluate(w02.evidence())
    assert decision["status"] == "DEFER_W01_EVENT_PREREGISTRATION"
    assert decision["ready"] is False
    assert decision["w01_event_preregistration_authorized"] is False
    assert decision["w01_return_screen_authorized"] is False
    assert decision["effective_action"] == "SOURCE_AND_REPRESENTATION_RESEARCH_ONLY"


def test_source_fixed_numeric_shape_is_ready_but_event_identity_is_not():
    e = w02.evidence()
    assert e["drawdown_window"]["ready"] is True
    assert e["drawdown_window"]["value"] == [3, 7]
    assert e["drawdown_magnitude"]["ready"] is True
    assert e["drawdown_magnitude"]["value"] == [0.20, 0.25]
    assert e["bear_state_handoff"]["ready"] is False
    assert e["leader_identity_basis"]["ready"] is False
    assert e["prior_wave_qualification"]["ready"] is False
    assert e["top_anchor_rule"]["ready"] is False
    assert e["first_pullback_rule"]["ready"] is False
    assert e["drawdown_basis"]["ready"] is False


def test_missing_required_field_fails_closed():
    e = w02.evidence()
    del e["top_anchor_rule"]
    decision = w02.evaluate(e)
    assert decision["ready"] is False
    assert decision["missing_fields"] == ["top_anchor_rule"]
    assert decision["w01_event_preregistration_authorized"] is False
    assert decision["w01_return_screen_authorized"] is False


def test_all_required_fields_only_authorize_separate_preregistration():
    e = copy.deepcopy(w02.evidence())
    for field in w02.REQUIRED:
        e[field] = {"ready": True, "detail": "independently grounded synthetic test evidence"}
    decision = w02.evaluate(e)
    assert decision["status"] == "READY_FOR_W01_EVENT_PREREGISTRATION"
    assert decision["ready"] is True
    assert decision["w01_event_preregistration_authorized"] is True
    assert decision["effective_action"] == "WRITE_SEPARATE_W01_EVENT_PREREGISTRATION"
    assert decision["w01_return_screen_authorized"] is False
    assert decision["x02_change_authorized"] is False
    assert decision["portfolio_combination_authorized"] is False
    assert decision["paper_trading_authorized"] is False
    assert decision["live_trading_authorized"] is False


def test_contract_freezes_source_numbers_and_forbids_parameter_search():
    c = w02.CONTRACT
    fixed = c["source_fixed"]
    assert fixed["drawdown_window_trading_sessions"] == [3, 7]
    assert fixed["drawdown_magnitude_fraction_approx"] == [0.20, 0.25]
    assert fixed["requires_bear_context"] is True
    assert fixed["requires_absolute_leader"] is True
    assert fixed["requires_first_post_top_event"] is True
    assert c["parameter_search"] is False
    assert c["w01_event_preregistration_authorized"] is False
    assert c["w01_return_screen_authorized"] is False
    assert c["x02_change_authorized"] is False
    assert c["portfolio_combination_authorized"] is False
    assert c["paper_trading_authorized"] is False
    assert c["live_trading_authorized"] is False


def test_l01_stage_proxy_is_not_silently_promoted_to_absolute_leader():
    detail = w02.evidence()["leader_identity_basis"]["detail"]
    assert "absolute leader" in detail
    assert "unique point-in-time" in detail
    assert w02.evidence()["leader_identity_basis"]["ready"] is False
