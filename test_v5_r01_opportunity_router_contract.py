import pytest

import v5_r01_opportunity_router_contract as r01


VALID_CLASSIFIER = {
    "contract_id": "future-c1",
    "status": "VALIDATED",
    "preregistered": True,
    "lineage_verified": True,
    "classifier_contract_sha256": "a" * 64,
    "validation_artifact_sha256": "b" * 64,
}


def test_unknown_fails_closed_to_cash():
    result = r01.route("UNKNOWN", sleeves=[{"name": "X", "authorization": "PAPER_ONLY", "evidence_id": "x1"}])
    assert result["effective_opportunity_state"] == "UNKNOWN"
    assert result["action"] == "CASH_ONLY"
    assert result["active_sleeves"] == []
    assert result["live_trading_authorized"] is False


def test_no_trade_fails_closed_even_with_authorized_sleeves():
    result = r01.route("NO_TRADE", sleeves=[{"name": "X", "authorization": "PAPER_ONLY", "evidence_id": "x1"}])
    assert result["action"] == "CASH_ONLY"
    assert result["active_sleeves"] == []


def test_opportunity_present_without_validated_classifier_is_downgraded_to_unknown():
    result = r01.route(
        "OPPORTUNITY_PRESENT",
        sleeves=[{"name": "X", "authorization": "PAPER_ONLY", "evidence_id": "x1"}],
        classifier={"contract_id": "future-c1", "status": "PROMISING", "preregistered": True},
    )
    assert result["effective_opportunity_state"] == "UNKNOWN"
    assert result["action"] == "CASH_ONLY"
    assert result["classifier_handoff_validation"]["valid"] is False
    assert any("artifact-bound" in reason for reason in result["reasons"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("lineage_verified", False),
        ("classifier_contract_sha256", "bad"),
        ("validation_artifact_sha256", ""),
        ("preregistered", False),
        ("status", "PROMISING"),
    ],
)
def test_classifier_handoff_fails_closed_when_lineage_envelope_is_incomplete(field, value):
    classifier = dict(VALID_CLASSIFIER)
    classifier[field] = value
    result = r01.route("OPPORTUNITY_PRESENT", classifier=classifier)
    assert result["effective_opportunity_state"] == "UNKNOWN"
    assert result["action"] == "CASH_ONLY"
    assert result["classifier_handoff_validation"]["valid"] is False


def test_validated_classifier_still_cannot_activate_unauthorized_sleeve():
    result = r01.route(
        "OPPORTUNITY_PRESENT",
        sleeves=[{"name": "FAILED", "authorization": "UNAUTHORIZED", "evidence_id": ""}],
        classifier=VALID_CLASSIFIER,
    )
    assert result["classifier_handoff_validation"] == {"valid": True, "reasons": []}
    assert result["effective_opportunity_state"] == "OPPORTUNITY_PRESENT"
    assert result["action"] == "CASH_ONLY"
    assert result["active_sleeves"] == []


def test_validated_classifier_routes_only_independently_authorized_sleeves():
    result = r01.route(
        "OPPORTUNITY_PRESENT",
        sleeves=[
            {"name": "A", "authorization": "RESEARCH_ONLY", "evidence_id": "a1"},
            {"name": "B", "authorization": "PAPER_ONLY", "evidence_id": "b1"},
            {"name": "C", "authorization": "UNAUTHORIZED", "evidence_id": ""},
        ],
        classifier=VALID_CLASSIFIER,
    )
    assert result["action"] == "ROUTE_TO_INDEPENDENTLY_AUTHORIZED_SLEEVES"
    assert result["active_sleeves"] == ["A", "B"]
    assert result["research_only_sleeves"] == ["A"]
    assert result["paper_only_sleeves"] == ["B"]
    assert result["live_trading_authorized"] is False
    assert result["portfolio_optimization_authorized"] is False


def test_authorized_sleeve_requires_evidence_id():
    with pytest.raises(ValueError, match="requires evidence_id"):
        r01.route("UNKNOWN", sleeves=[{"name": "X", "authorization": "PAPER_ONLY"}])


def test_duplicate_sleeves_are_rejected():
    with pytest.raises(ValueError, match="duplicate sleeve"):
        r01.route(
            "UNKNOWN",
            sleeves=[
                {"name": "X", "authorization": "UNAUTHORIZED"},
                {"name": "X", "authorization": "UNAUTHORIZED"},
            ],
        )


def test_contract_does_not_smuggle_in_a_numeric_classifier_or_live_authority():
    assert r01.CONTRACT["version"] == "V5_R01_OPPORTUNITY_ROUTER_CONTRACT_V2"
    assert r01.CONTRACT["numeric_regime_classifier_implemented"] is False
    assert r01.CONTRACT["router_does_not_self_verify_external_classifier_files"] is True
    assert r01.CONTRACT["parameter_search"] is False
    assert r01.CONTRACT["alpha_evaluation_authorized"] is False
    assert r01.CONTRACT["portfolio_optimization_authorized"] is False
    assert r01.CONTRACT["live_trading_authorized"] is False
