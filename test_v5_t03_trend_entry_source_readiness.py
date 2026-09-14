import copy

import v5_t03_trend_entry_source_readiness as t03


def test_current_source_defers_trend_entry_preregistration():
    d = t03.evaluate(t03.evidence())
    assert d["status"] == "DEFER_TREND_ENTRY_PREREGISTRATION"
    assert d["ready"] is False
    assert d["trend_entry_preregistration_authorized"] is False
    assert d["trend_return_screen_authorized"] is False
    assert d["t02_combination_authorized"] is False
    assert d["effective_action"] == "SOURCE_AND_TREND_STATE_REPRESENTATION_ONLY"


def test_numeric_source_literals_do_not_define_trend_state():
    e = t03.evidence()
    assert e["literal_ma12"]["ready"] is True
    assert e["literal_ma20"]["ready"] is True
    assert e["literal_acute_selloff_20pct"]["ready"] is True
    assert e["trend_stock_predicate"]["ready"] is False


def test_ma_period_does_not_define_touch_or_break_semantics():
    e = t03.evidence()
    assert e["ma12_low_buy_observation_rule"]["ready"] is False
    assert e["ma12_proximity_or_cross_semantics"]["ready"] is False
    assert e["ma20_break_observation_rule"]["ready"] is False
    assert e["ma20_caution_action_semantics"]["ready"] is False


def test_acute_20pct_does_not_define_anchor_or_window():
    e = t03.evidence()
    assert e["acute_selloff_anchor"]["ready"] is False
    assert e["acute_selloff_measurement_formula"]["ready"] is False
    assert e["acute_selloff_window"]["ready"] is False


def test_missing_required_field_fails_closed():
    e = t03.evidence()
    del e["condition_interaction_precedence"]
    d = t03.evaluate(e)
    assert d["ready"] is False
    assert d["missing_fields"] == ["condition_interaction_precedence"]


def test_all_required_fields_only_authorize_separate_preregistration():
    e = copy.deepcopy(t03.evidence())
    for field in t03.REQUIRED:
        e[field] = {"ready": True, "detail": "independently grounded synthetic evidence"}
    d = t03.evaluate(e)
    assert d["status"] == "READY_FOR_TREND_ENTRY_PREREGISTRATION"
    assert d["trend_entry_preregistration_authorized"] is True
    assert d["trend_return_screen_authorized"] is False
    assert d["t02_combination_authorized"] is False
    assert d["paper_trading_authorized"] is False
    assert d["live_trading_authorized"] is False


def test_contract_freezes_source_numbers_and_forbids_promotion():
    c = t03.CONTRACT
    assert c["source_fixed"]["low_buy_ma_period_sessions"] == 12
    assert c["source_fixed"]["caution_ma_period_sessions"] == 20
    assert c["source_fixed"]["acute_selloff_fraction_approx"] == 0.20
    assert c["parameter_search"] is False
    assert c["trend_return_screen_authorized"] is False
    assert c["t02_combination_authorized"] is False
    assert c["x02_change_authorized"] is False
    assert c["portfolio_combination_authorized"] is False
    assert c["paper_trading_authorized"] is False
    assert c["live_trading_authorized"] is False
