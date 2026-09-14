import copy

import v5_w05_rebound_context_source_readiness as w05


def test_current_evidence_defers_rebound_context_preregistration():
    d = w05.evaluate(w05.evidence())
    assert d["status"] == "DEFER_REBOUND_CONTEXT_PREREGISTRATION"
    assert d["ready"] is False
    assert d["rebound_context_preregistration_authorized"] is False
    assert d["w01_event_preregistration_authorized"] is False
    assert d["w01_return_screen_authorized"] is False
    assert d["effective_action"] == "SOURCE_AND_REPRESENTATION_RESEARCH_ONLY"


def test_literal_sequence_is_preserved_without_inventing_scope():
    fixed = w05.CONTRACT["source_fixed"]
    assert fixed["sequence"][:3] == ["bear_market_context", "large_rebound", "leader_top"]
    assert fixed["drawdown_window_trading_sessions_approx"] == [3, 7]
    assert fixed["drawdown_fraction_approx"] == [0.20, 0.25]
    e = w05.evidence()
    assert e["literal_bear_context"]["ready"] is True
    assert e["literal_large_rebound_precedes_top"]["ready"] is True
    assert e["rebound_scope"]["ready"] is False
    assert e["rebound_reference_series"]["ready"] is False


def test_large_rebound_is_not_silently_stock_prior_wave():
    assert w05.CONTRACT["semantic_guard"] == "large rebound is not silently redefined as a stock-specific prior wave"
    assert w05.evidence()["rebound_scope"]["ready"] is False


def test_prior_high_area_is_not_silently_promoted_to_exit_rule():
    assert w05.CONTRACT["source_fixed"]["prior_high_area_is_descriptive_not_exit_rule"] is True
    e = w05.evidence()
    assert e["literal_prior_high_area_outcome"]["ready"] is True
    assert e["prior_high_reference"]["ready"] is False
    assert e["prior_high_near_definition"]["ready"] is False
    assert e["post_entry_target_role"]["ready"] is False


def test_missing_required_field_fails_closed():
    e = w05.evidence()
    del e["rebound_end_anchor"]
    d = w05.evaluate(e)
    assert d["ready"] is False
    assert d["missing_fields"] == ["rebound_end_anchor"]
    assert d["rebound_context_preregistration_authorized"] is False


def test_all_ready_only_authorizes_separate_preregistration():
    e = copy.deepcopy(w05.evidence())
    for field in w05.REQUIRED:
        e[field] = {"ready": True, "detail": "synthetic independent evidence"}
    d = w05.evaluate(e)
    assert d["status"] == "READY_FOR_REBOUND_CONTEXT_PREREGISTRATION"
    assert d["rebound_context_preregistration_authorized"] is True
    assert d["effective_action"] == "WRITE_SEPARATE_REBOUND_CONTEXT_PREREGISTRATION"
    assert d["w01_event_preregistration_authorized"] is False
    assert d["w01_return_screen_authorized"] is False
    assert d["x02_change_authorized"] is False
    assert d["portfolio_combination_authorized"] is False
    assert d["paper_trading_authorized"] is False
    assert d["live_trading_authorized"] is False


def test_parameter_search_and_trading_are_forbidden():
    c = w05.CONTRACT
    assert c["parameter_search"] is False
    assert c["x02_change_authorized"] is False
    assert c["portfolio_combination_authorized"] is False
    assert c["paper_trading_authorized"] is False
    assert c["live_trading_authorized"] is False
