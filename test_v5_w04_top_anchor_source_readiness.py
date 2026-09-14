import copy

import v5_w04_top_anchor_source_readiness as w04


def test_current_evidence_defers_top_anchor_preregistration():
    d = w04.evaluate(w04.evidence())
    assert d["status"] == "DEFER_TOP_ANCHOR_PREREGISTRATION"
    assert d["ready"] is False
    assert d["top_anchor_preregistration_authorized"] is False
    assert d["w01_event_preregistration_authorized"] is False
    assert d["w01_return_screen_authorized"] is False


def test_source_shape_stays_frozen_while_measurement_semantics_do_not():
    fixed = w04.CONTRACT["source_fixed"]
    assert fixed["event_order"] == ["leader_top", "decline", "first_left_side_opportunity"]
    assert fixed["elapsed_trading_sessions_approx"] == [3, 7]
    assert fixed["decline_fraction_approx"] == [0.20, 0.25]
    e = w04.evidence()
    assert e["top_price_field"]["ready"] is False
    assert e["top_confirmation_rule"]["ready"] is False
    assert e["drawdown_observation_field"]["ready"] is False
    assert e["drawdown_formula"]["ready"] is False


def test_unrelated_three_day_trend_rule_is_not_transferred():
    assert w04.CONTRACT["non_transfer_rule"] == "trend-stock three-day-no-new-high exit rule is not a W01 top definition"
    e = w04.evidence()["trend_three_day_exit_transfer"]
    assert e["ready"] is False
    assert "not transferred" in e["detail"]


def test_missing_required_field_fails_closed():
    e = w04.evidence()
    del e["drawdown_formula"]
    d = w04.evaluate(e)
    assert d["ready"] is False
    assert d["missing_fields"] == ["drawdown_formula"]


def test_all_ready_only_authorizes_separate_top_anchor_preregistration():
    e = copy.deepcopy(w04.evidence())
    for field in w04.REQUIRED:
        e[field] = {"ready": True, "detail": "synthetic independent evidence"}
    d = w04.evaluate(e)
    assert d["status"] == "READY_FOR_TOP_ANCHOR_PREREGISTRATION"
    assert d["top_anchor_preregistration_authorized"] is True
    assert d["effective_action"] == "WRITE_SEPARATE_TOP_ANCHOR_PREREGISTRATION"
    assert d["w01_event_preregistration_authorized"] is False
    assert d["w01_return_screen_authorized"] is False
    assert d["paper_trading_authorized"] is False
    assert d["live_trading_authorized"] is False


def test_parameter_search_and_trading_are_forbidden():
    c = w04.CONTRACT
    assert c["parameter_search"] is False
    assert c["x02_change_authorized"] is False
    assert c["portfolio_combination_authorized"] is False
    assert c["paper_trading_authorized"] is False
    assert c["live_trading_authorized"] is False
