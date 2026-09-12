import pandas as pd

from v4_17_event_source_audit import load_eastmoney


def test_canonical_loader_and_legacy_precedence(tmp_path):
    annual = tmp_path / 'year=2021'
    annual.mkdir()
    row = dict(schema_version='v4.17-a.2', source_provider='eastmoney',
               source_endpoint='akshare.stock_notice_report',
               event_type='corporate_announcement', stock_code_raw='000001',
               published_date='2021-01-04', title='测试公告')
    pd.DataFrame([row]).to_parquet(annual / 'notices_2021.parquet')
    pd.DataFrame([dict(security_code='000002', published_date='2021-01-05',
                       title='旧格式')]).to_parquet(tmp_path / 'legacy.parquet')
    frame, diag = load_eastmoney(str(tmp_path / '**' / '*.parquet'))
    assert diag['loader_validation_pass']
    assert diag['canonical_years'] == [2021]
    assert diag['legacy_rows_excluded_by_canonical_year'] == 1
    assert frame['security_code'].tolist() == ['000001']


def test_annual_path_cannot_fall_back_to_legacy(tmp_path):
    annual = tmp_path / 'year=2021'
    annual.mkdir()
    pd.DataFrame([dict(security_code='000001', published_date='2021-01-04',
                       title='测试公告')]).to_parquet(annual / 'notices_2021.parquet')
    frame, diag = load_eastmoney(str(tmp_path / '**' / '*.parquet'))
    assert frame.empty
    assert not diag['loader_validation_pass']
    assert len(diag['canonical_contract_violations']) == 1
