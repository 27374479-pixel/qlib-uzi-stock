import pandas as pd
import v4_3_long_only_portfolio as engine


def test_ranking_does_not_use_exit_outcomes():
    frame = pd.DataFrame(dict(trade_date=pd.to_datetime(['2024-01-02']*4),
                              instrument=['A','B','C','D'], score=[.9,.8,.7,.6],
                              clean_mom20_rank=[.9,.8,.7,.6], exit_1000=[1,2,3,4]))
    selected = engine._select_top(frame,3).instrument.tolist()
    frame['exit_1000'] = [100,-100,200,1000]
    assert engine._select_top(frame,3).instrument.tolist() == selected == ['A','B','C']


def test_underfilled_day_stays_cash_in_legacy_spec():
    frame = pd.DataFrame(dict(trade_date=pd.to_datetime(['2024-01-02']*2),
                              instrument=['A','B'], score=[.9,.8],clean_mom20_rank=[.9,.8]))
    assert engine._select_top(frame,3).empty


def test_legacy_missing_exit_is_explicitly_characterized():
    frame = pd.DataFrame(dict(trade_date=pd.to_datetime(['2024-01-02']*2),
                              entry_1445=[10.,10.],exit_1000=[11.,float('nan')]))
    series, ledger = engine._portfolio_series(frame,[pd.Timestamp('2024-01-02')],'10:00','BASE')
    assert len(ledger) == 1  # Diagnostic: legacy code reallocates to surviving rows.
    assert series.iloc[0] > .09
