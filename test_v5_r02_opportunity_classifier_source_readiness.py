import copy

import v5_r02_opportunity_classifier_source_readiness as r02


def test_current_book_evidence_defers_numeric_classifier_preregistration():
    result = r02.evaluate(r02.DEFAULT_EVIDENCE)
    assert result["status"] == "DEFER_NUMERIC_CLASSIFIER_PREREGISTRATION"
    assert result["ready"] is False
    assert result["classifier_preregistration_authorized"] is False
    assert result["classifier_return_screen_authorized"] is False
    assert result["effective_opportunity_state"] == "UNKNOWN"
    assert result["action"] == "CASH_ONLY"


def test_architecture_evidence_alone_cannot_activate_classifier():
    result = r02.evaluate(r02.DEFAULT_EVIDENCE)
    failed = {item["field"] for item in result["not_ready"]}
    assert "point_in_time_market_opportunity_observable" in failed
    assert "deterministic_state_mapping" in failed
    assert "numeric_threshold_basis_if_required" in failed
    assert "noncircular_validation_target" in failed


def test_missing_required_field_fails_closed():
    evidence = copy.deepcopy(r02.DEFAULT_EVIDENCE)
    del evidence["deterministic_state_mapping"]
    result = r02.evaluate(evidence)
    assert result["status"] == "DEFER_NUMERIC_CLASSIFIER_PREREGISTRATION"
    assert result["missing_fields"] == ["deterministic_state_mapping"]
    assert result["action"] == "CASH_ONLY"


def test_future_complete_source_evidence_only_authorizes_preregistration_not_return_screen():
    evidence = copy.deepcopy(r02.DEFAULT_EVIDENCE)
    for field in r02.REQUIRED_FOR_CLASSIFIER_PREREGISTRATION:
        evidence[field] = {"ready": True, "detail": "future independently established source/representation evidence"}
    result = r02.evaluate(evidence)
    assert result["status"] == "READY_FOR_NUMERIC_CLASSIFIER_PREREGISTRATION"
    assert result["classifier_preregistration_authorized"] is True
    assert result["classifier_return_screen_authorized"] is False
    assert result["numeric_classifier_implemented"] is False
    assert result["paper_trading_authorized"] is False
    assert result["live_trading_authorized"] is False


def test_contract_forbids_threshold_search_and_x02_gate_changes():
    assert r02.CONTRACT["parameter_search"] is False
    assert r02.CONTRACT["numeric_classifier_implemented"] is False
    assert r02.CONTRACT["classifier_return_screen_authorized"] is False
    assert r02.CONTRACT["x02_gate_change_authorized"] is False
    assert r02.CONTRACT["portfolio_optimization_authorized"] is False
    assert r02.CONTRACT["fallback"] == "UNKNOWN -> CASH_ONLY"
