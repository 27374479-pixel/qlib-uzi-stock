import pandas as pd

from v4_18_event_text_features import text_tokens
from v4_18_prepare_event_text_audit import load_events, stratified_event_sample


def test_lazy_tokens_preserve_eligible_sample(tmp_path):
    titles = ['测试合同', '董', '', 'abc', '新能源产品', '重大合同']
    rows = [dict(event_id=str(i), instrument='sz.000001', stock_name='',
                 title=title, announcement_type='公告', published_date='2021-01-01',
                 available_trade_date='2021-01-04', causal_status='AVAILABLE_NEXT_SESSION',
                 calendar_sha256='hash') for i, title in enumerate(titles)]
    path = tmp_path / 'events.parquet'
    pd.DataFrame(rows).to_parquet(path)
    events = load_events(path, 'hash', {'2021-01-04': 0})
    assert 'tokens' not in events.columns
    assert set(events.event_id) == {'0', '3', '4', '5'}
    expected = events.nsmallest(3, '_rank').sort_values(['available_trade_date', 'event_id'])
    actual = stratified_event_sample(events, 3)
    assert actual.event_id.tolist() == expected.event_id.tolist()
    assert actual.tokens.tolist() == expected.normalized_title.map(text_tokens).tolist()
