import copy

import v5_m02_market_cycle_source_readiness as m02


def test_current_book_evidence_defers_classifier_preregistration():
    decision = m02.evaluate(m02.evidence())
    assert decision["status"] == "DEFER_MARKET_CYCLE_CLASSIFIER_PREREGISTRATION"
    assert decision["ready"] is False
    assert decision["classifier_preregistration_authorized"] is False
    assert decision["return_screen_authorized"] is False
    assert decision["w01_return_screen_authorized"] is False
    assert decision["effective_action"] == "SOURCE_AND_INDEPENDENT_TARGET_RESEARCH_ONLY"


def test_raw_m01_representation_is_not_semantic_state_mapping():
    e = m02.evidence()
    assert e["m01_structural_representation"]["ready"] is True
    assert e["observable_to_state_mapping"]["ready"] is False
    assert e["threshold_or_boundary_basis"]["ready"] is False
    assert e["independent_validation_target"]["ready"] is False


def test_missing_required_field_fails_closed():
    e = m02.evidence()
    del e["ambiguity_policy"]
    decision = m02.evaluate(e)
    assert decision["ready"] is False
    assert decision["missing_fields"] == ["ambiguity_policy"]
    assert decision["classifier_preregistration_authorized"] is False


def test_all_required_fields_only_authorize_new_preregistration():
    e = copy.deepcopy(m02.evidence())
    for field in m02.REQUIRED:
        e[field] = {"ready": True, "detail": "independently grounded synthetic test evidence"}
    decision = m02.evaluate(e)
    assert decision["status"] == "READY_FOR_MARKET_CYCLE_CLASSIFIER_PREREGISTRATION"
    assert decision["classifier_preregistration_authorized"] is True
    assert decision["effective_action"] == "WRITE_SEPARATE_CLASSIFIER_PREREGISTRATION"
    assert decision["return_screen_authorized"] is False
    assert decision["w01_return_screen_authorized"] is False
    assert decision["paper_trading_authorized"] is False
    assert decision["live_trading_authorized"] is False


def test_contract_prohibits_strategy_return_threshold_search():
    c = m02.CONTRACT
    assert c["parameter_search"] is False
    assert c["classifier_preregistration_authorized"] is False
    assert c["return_screen_authorized"] is False
    assert c["w01_return_screen_authorized"] is False
    assert c["x02_change_authorized"] is False
    assert c["portfolio_combination_authorized"] is False
    assert c["paper_trading_authorized"] is False
    assert c["live_trading_authorized"] is False
