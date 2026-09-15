import v5_m06_recovery_transition_readiness as mod


def test_current_evidence_defers():
    d = mod.evaluate(mod.evidence())
    assert d["status"] == "DEFER_BEAR_RECOVERY_TRANSITION_PREREGISTRATION"
    assert d["ready"] is False
    assert d["recovery_transition_preregistration_authorized"] is False
    assert d["return_screen_authorized"] is False
    assert d["w01_return_screen_authorized"] is False


def test_source_guards_are_fixed():
    fixed = mod.CONTRACT["source_fixed"]
    assert fixed["market_is_cyclical"] is True
    assert fixed["large_prior_decline_is_not_sufficient"] is True
    assert fixed["decline_settling_precedes_recovery"] is True
    assert mod.CONTRACT["parameter_search"] is False


def test_lineage_ready_is_not_enough():
    e = mod.evidence()
    assert e["m01_m04_m05_lineage_binding"]["ready"] is True
    assert mod.evaluate(e)["ready"] is False


def test_missing_field_fails_closed():
    e = mod.evidence()
    del e["persistence_rule"]
    d = mod.evaluate(e)
    assert d["ready"] is False
    assert "persistence_rule" in d["missing_fields"]


def test_all_required_ready_only_allows_new_preregistration():
    e = mod.evidence()
    for field in mod.REQUIRED:
        e[field]["ready"] = True
    d = mod.evaluate(e)
    assert d["ready"] is True
    assert d["recovery_transition_preregistration_authorized"] is True
    assert d["return_screen_authorized"] is False
    assert d["w01_return_screen_authorized"] is False
    assert d["paper_trading_authorized"] is False
    assert d["live_trading_authorized"] is False
