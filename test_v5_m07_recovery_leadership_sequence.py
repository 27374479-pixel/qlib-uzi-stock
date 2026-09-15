import copy

import v5_m07_recovery_leadership_sequence as m07


def test_current_state_keeps_mapping_deferred():
    d = m07.evaluate(m07.evidence())
    assert d["ontology_ready"] is True
    assert d["quantitative_mapping_ready"] is False
    assert d["status"] == "ONTOLOGY_READY_TWO_STAGE_MAPPING_DEFERRED"


def test_source_semantic_order_is_frozen():
    assert m07.CONTRACT["semantic_order"] == [
        "RECOVERY_ONSET_CONTEXT",
        "LEADERSHIP_EMERGENCE_CONTEXT",
    ]
    assert m07.CONTRACT["m06_rescue_authorized"] is False


def test_missing_required_mapping_field_fails_closed():
    e = m07.evidence()
    del e["transition_lag_structure"]
    d = m07.evaluate(e)
    assert d["quantitative_mapping_ready"] is False
    assert "transition_lag_structure" in d["missing_fields"]


def test_all_mapping_fields_ready_only_authorizes_new_preregistration():
    e = copy.deepcopy(m07.evidence())
    for field in m07.REQUIRED_FOR_NEXT_PREREG:
        e[field] = {"ready": True, "detail": "synthetic independent evidence"}
    d = m07.evaluate(e)
    assert d["status"] == "READY_FOR_TWO_STAGE_VALIDATION_PREREGISTRATION"
    assert d["quantitative_mapping_ready"] is True
    assert d["historical_state_labels_authorized"] is False
    assert d["w01_return_screen_authorized"] is False
    assert d["paper_trading_authorized"] is False
    assert d["live_trading_authorized"] is False
