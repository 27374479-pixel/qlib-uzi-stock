import copy
import v5_w07_left_side_resonance_source_readiness as w07


def test_current_source_defers_resonance_preregistration():
    d=w07.evaluate(w07.evidence())
    assert d['status']=='DEFER_LEFT_SIDE_RESONANCE_PREREGISTRATION'
    assert d['ready'] is False
    assert d['resonance_preregistration_authorized'] is False
    assert d['w01_return_screen_authorized'] is False
    assert d['effective_action']=='SOURCE_AND_REPRESENTATION_RESEARCH_ONLY'


def test_literal_resonance_does_not_define_states():
    e=w07.evidence()
    assert e['literal_market_stock_resonance']['ready'] is True
    assert e['market_left_side_state']['ready'] is False
    assert e['stock_left_side_state']['ready'] is False
    assert e['resonance_operator']['ready'] is False


def test_critical_point_is_named_but_not_machine_ready():
    e=w07.evidence()
    assert e['literal_waiting_and_critical_point']['ready'] is True
    assert e['critical_point_definition']['ready'] is False
    assert e['entry_execution_time']['ready'] is False


def test_missing_required_field_fails_closed():
    e=w07.evidence(); del e['mismatch_policy']
    d=w07.evaluate(e)
    assert d['ready'] is False
    assert d['missing_fields']==['mismatch_policy']


def test_all_required_fields_only_authorize_separate_preregistration():
    e=copy.deepcopy(w07.evidence())
    for f in w07.REQUIRED: e[f]={'ready':True,'detail':'independently grounded synthetic evidence'}
    d=w07.evaluate(e)
    assert d['status']=='READY_FOR_LEFT_SIDE_RESONANCE_PREREGISTRATION'
    assert d['resonance_preregistration_authorized'] is True
    assert d['w01_event_preregistration_authorized'] is False
    assert d['w01_return_screen_authorized'] is False
    assert d['paper_trading_authorized'] is False
    assert d['live_trading_authorized'] is False


def test_contract_preserves_source_architecture_without_thresholds():
    c=w07.CONTRACT
    assert c['source_fixed']['market_stock_resonance_required'] is True
    assert c['source_fixed']['waiting_is_part_of_method'] is True
    assert c['source_fixed']['critical_point_named_but_not_numeric'] is True
    assert c['parameter_search'] is False


def test_contract_forbids_strategy_and_trading_promotion():
    c=w07.CONTRACT
    assert c['w01_return_screen_authorized'] is False
    assert c['x02_change_authorized'] is False
    assert c['portfolio_combination_authorized'] is False
    assert c['paper_trading_authorized'] is False
    assert c['live_trading_authorized'] is False
