import pytest
from event_context_candidate_v2 import route_title


@pytest.mark.parametrize('title', ['甲公司:2025年年度报告摘要', '乙公司:董事会决议公告', '公司:募集资金三方监管协议'])
def test_routine_never_forms_theme(title):
    result = route_title(title)
    assert result['routing_status'] == 'ROUTINE_TITLE'
    assert not result['theme_assignment_allowed']


@pytest.mark.parametrize('title', ['公司:关于重大销售合同的公告', '公司:关于药品注册获批的公告', '公司:关于董事会审议收购项目的公告'])
def test_action_requires_body_not_automatic_theme(title):
    result = route_title(title)
    assert result['routing_status'] == 'BODY_REVIEW_REQUIRED'
    assert not result['theme_assignment_allowed']


def test_unknown_abstains():
    assert route_title('澄清公告')['routing_status'] == 'UNRESOLVED_TITLE'
