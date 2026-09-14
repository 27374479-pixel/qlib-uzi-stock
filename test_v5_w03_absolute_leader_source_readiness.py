import copy

import v5_w03_absolute_leader_source_readiness as w03


def test_current_evidence_defers_absolute_leader_preregistration():
    d = w03.evaluate(w03.evidence())
    assert d["status"] == "DEFER_ABSOLUTE_LEADER_PREREGISTRATION"
    assert d["ready"] is False
    assert d["absolute_leader_preregistration_authorized"] is False
    assert d["w01_event_preregistration_authorized"] is False
    assert d["w01_return_screen_authorized"] is False


def test_source_traits_are_frozen_but_classifier_semantics_are_not():
    e = w03.evidence()
    assert e["trait_set_transcription"]["ready"] is True
    assert e["trait_necessity_or_combination_rule"]["ready"] is False
    assert e["unique_selection_or_ranking_rule"]["ready"] is False
    assert e["tie_break_rule"]["ready"] is False
    assert e["identity_known_time"]["ready"] is False
    assert e["no_retroactive_identity_rule"]["ready"] is False


def test_direct_source_numbers_are_preserved_without_becoming_classifier():
    c = w03.CONTRACT
    direct = c["direct_numeric_or_literal_traits"]
    assert direct["three_board_launch"] is True
    assert direct["disagreement_turnover_cny_floor"] == 1_000_000_000
    assert direct["launch_price_cny_ceiling_exclusive"] == 10.0
    assert c["absolute_leader_preregistration_authorized"] is False


def test_missing_required_field_fails_closed():
    e = w03.evidence()
    del e["tie_break_rule"]
    d = w03.evaluate(e)
    assert d["ready"] is False
    assert d["missing_fields"] == ["tie_break_rule"]


def test_all_ready_only_authorizes_separate_leader_preregistration():
    e = copy.deepcopy(w03.evidence())
    for field in w03.REQUIRED:
        e[field] = {"ready": True, "detail": "synthetic independent evidence"}
    d = w03.evaluate(e)
    assert d["status"] == "READY_FOR_ABSOLUTE_LEADER_PREREGISTRATION"
    assert d["absolute_leader_preregistration_authorized"] is True
    assert d["effective_action"] == "WRITE_SEPARATE_ABSOLUTE_LEADER_PREREGISTRATION"
    assert d["w01_event_preregistration_authorized"] is False
    assert d["w01_return_screen_authorized"] is False
    assert d["paper_trading_authorized"] is False
    assert d["live_trading_authorized"] is False


def test_parameter_search_and_retroactive_promotion_are_forbidden():
    assert w03.CONTRACT["parameter_search"] is False
    assert w03.evidence()["no_retroactive_identity_rule"]["ready"] is False
    assert w03.CONTRACT["x02_change_authorized"] is False
    assert w03.CONTRACT["portfolio_combination_authorized"] is False
