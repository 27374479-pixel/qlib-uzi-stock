import v5_m03_market_cycle_ontology as mod


def test_current_result_is_ontology_ready_mapping_deferred():
    d = mod.evaluate(mod.evidence())
    assert d["status"] == "ONTOLOGY_READY_MAPPING_DEFERRED"
    assert d["ontology_ready"] is True
    assert d["mapping_ready"] is False
    assert d["date_classification_authorized"] is False
    assert d["return_screen_authorized"] is False


def test_source_vocabulary_is_frozen_and_small():
    assert mod.SOURCE_STATES == (
        "BEAR_DECLINE_CONTEXT",
        "BEAR_RECOVERY_CONTEXT",
        "BULL_BROADENING_CONTEXT",
    )
    assert mod.SYSTEM_FALLBACK == "UNKNOWN"


def test_all_mapping_fields_ready_only_authorizes_new_preregistration():
    e = mod.evidence()
    for key in mod.REQUIRED_FOR_MAPPING_PREREGISTRATION:
        e[key]["ready"] = True
    d = mod.evaluate(e)
    assert d["mapping_ready"] is True
    assert d["mapping_preregistration_authorized"] is True
    assert d["date_classification_authorized"] is False
    assert d["return_screen_authorized"] is False
    assert d["paper_trading_authorized"] is False
    assert d["live_trading_authorized"] is False


def test_one_unready_mapping_field_fails_closed():
    e = mod.evidence()
    for key in mod.REQUIRED_FOR_MAPPING_PREREGISTRATION:
        e[key]["ready"] = True
    e["independent_validation_target"]["ready"] = False
    assert mod.evaluate(e)["mapping_ready"] is False
