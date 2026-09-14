import copy
import v5_w09_top_anchor_readiness as w09


def test_current_source_defers():
    d = w09.evaluate(w09.evidence())
    assert d["status"] == "DEFER_TOP_ANCHOR_PREREGISTRATION"
    assert d["ready"] is False
    assert d["w01_return_screen_authorized"] is False


def test_missing_semantic_field_fails_closed():
    e = w09.evidence()
    del e["confirmation_rule"]
    d = w09.evaluate(e)
    assert d["ready"] is False
    assert "confirmation_rule" in d["missing_fields"]


def test_upstream_lineage_is_not_enough():
    e = w09.evidence()
    assert e["w08_lineage_binding"]["ready"] is True
    assert w09.evaluate(e)["ready"] is False


def test_all_ready_only_authorizes_separate_preregistration():
    e = copy.deepcopy(w09.evidence())
    for key in w09.REQUIRED:
        e[key]["ready"] = True
    d = w09.evaluate(e)
    assert d["ready"] is True
    assert d["top_anchor_preregistration_authorized"] is True
    assert d["w01_return_screen_authorized"] is False
    assert d["paper_trading_authorized"] is False
    assert d["live_trading_authorized"] is False
