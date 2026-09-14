import v5_w08_leader_identity_source_readiness as w08


def test_current_source_defers():
    d=w08.evaluate(w08.evidence())
    assert d["ready"] is False
    assert d["status"]=="DEFER_LEADER_IDENTITY_PREREGISTRATION"


def test_all_fields_required():
    e={k:True for k in w08.FIELDS}
    assert w08.evaluate(e)["ready"] is True
    e["leader_scope"]=False
    assert w08.evaluate(e)["ready"] is False


def test_current_lineage_ready_but_semantics_not_ready():
    e=w08.evidence()
    assert e["causal_lineage"] is True
    assert e["w01_binding"] is True
    assert e["identity_observables"] is False
