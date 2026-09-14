import copy
import v5_m07_recovery_state_readiness as m07


def test_current_evidence_defers():
    d = m07.evaluate(m07.evidence())
    assert d["status"] == "DEFER_RECOVERY_STATE_PREREGISTRATION"
    assert d["ready"] is False
    assert d["w01_return_screen_authorized"] is False


def test_missing_field_fails_closed():
    e = m07.evidence()
    del e["ambiguity_policy"]
    d = m07.evaluate(e)
    assert d["ready"] is False
    assert "ambiguity_policy" in d["missing_fields"]


def test_all_fields_only_authorize_new_preregistration():
    e = copy.deepcopy(m07.evidence())
    for k in m07.REQUIRED:
        e[k]["ready"] = True
    d = m07.evaluate(e)
    assert d["ready"] is True
    assert d["state_preregistration_authorized"] is True
    assert d["return_screen_authorized"] is False
    assert d["w01_return_screen_authorized"] is False
    assert d["paper_trading_authorized"] is False
    assert d["live_trading_authorized"] is False
