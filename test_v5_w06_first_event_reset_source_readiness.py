import copy

import v5_w06_first_event_reset_source_readiness as w06


def test_current_source_defers_first_event_reset_preregistration():
    d = w06.evaluate(w06.evidence())
    assert d["status"] == "DEFER_FIRST_EVENT_RESET_PREREGISTRATION"
    assert d["ready"] is False
    assert d["first_event_reset_preregistration_authorized"] is False
    assert d["w01_event_preregistration_authorized"] is False
    assert d["w01_return_screen_authorized"] is False
    assert d["effective_action"] == "SOURCE_AND_STATE_MACHINE_RESEARCH_ONLY"


def test_literal_firstness_does_not_make_state_machine_ready():
    e = w06.evidence()
    assert e["literal_firstness"]["ready"] is True
    assert e["literal_window_and_drawdown_shape"]["ready"] is True
    assert e["first_event_predicate"]["ready"] is False
    assert e["event_consumption_rule"]["ready"] is False
    assert e["pre_entry_new_high_reset_rule"]["ready"] is False


def test_post_entry_new_high_does_not_define_pre_entry_reset():
    e = w06.evidence()
    assert e["post_entry_new_high_is_distinct"]["ready"] is True
    assert e["pre_entry_new_high_reset_rule"]["ready"] is False
    assert e["replacement_top_rule"]["ready"] is False


def test_missing_required_field_fails_closed():
    e = w06.evidence()
    del e["failed_or_unfilled_event_policy"]
    d = w06.evaluate(e)
    assert d["ready"] is False
    assert d["missing_fields"] == ["failed_or_unfilled_event_policy"]
    assert d["first_event_reset_preregistration_authorized"] is False


def test_all_required_fields_only_authorize_separate_preregistration():
    e = copy.deepcopy(w06.evidence())
    for field in w06.REQUIRED:
        e[field] = {"ready": True, "detail": "independently grounded synthetic evidence"}
    d = w06.evaluate(e)
    assert d["status"] == "READY_FOR_FIRST_EVENT_RESET_PREREGISTRATION"
    assert d["first_event_reset_preregistration_authorized"] is True
    assert d["effective_action"] == "WRITE_SEPARATE_FIRST_EVENT_RESET_PREREGISTRATION"
    assert d["w01_event_preregistration_authorized"] is False
    assert d["w01_return_screen_authorized"] is False
    assert d["paper_trading_authorized"] is False
    assert d["live_trading_authorized"] is False


def test_contract_preserves_source_shape_and_forbids_later_candidate_rescue():
    c = w06.CONTRACT
    assert c["source_fixed"]["ordinal_requirement"] == "first_post_top_left_side_opportunity"
    assert c["source_fixed"]["drawdown_window_trading_sessions_approx"] == [3, 7]
    assert c["source_fixed"]["drawdown_fraction_approx"] == [0.20, 0.25]
    assert c["source_fixed"]["later_candidates_may_not_replace_first_based_on_pnl"] is True
    assert c["source_fixed"]["post_entry_new_high_description_is_not_pre_entry_reset_rule"] is True


def test_contract_forbids_strategy_and_trading_promotion():
    c = w06.CONTRACT
    assert c["parameter_search"] is False
    assert c["first_event_reset_preregistration_authorized"] is False
    assert c["w01_event_preregistration_authorized"] is False
    assert c["w01_return_screen_authorized"] is False
    assert c["x02_change_authorized"] is False
    assert c["portfolio_combination_authorized"] is False
    assert c["paper_trading_authorized"] is False
    assert c["live_trading_authorized"] is False
