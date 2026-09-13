import pandas as pd
import v4_3_long_only_portfolio as engine
from reproduce_x02_local import restrict_to_complete_exit_horizon


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


def test_complete_exit_horizon_drops_whole_trade_date_before_selection():
    frame = pd.DataFrame({
        'trade_date': pd.to_datetime(['2026-07-15', '2026-07-16', '2026-07-16']),
        'exit_date': pd.to_datetime(['2026-07-16', '2026-07-17', '2026-07-17']),
        'instrument': ['A', 'B', 'C'],
        'score': [0.1, 0.99, 0.98],
    })
    kept, excluded = restrict_to_complete_exit_horizon(frame, pd.Timestamp('2026-07-16'))
    assert kept['trade_date'].dt.strftime('%Y-%m-%d').unique().tolist() == ['2026-07-15']
    assert [pd.Timestamp(x).strftime('%Y-%m-%d') for x in excluded] == ['2026-07-16']
    assert set(kept['instrument']) == {'A'}


def test_complete_exit_horizon_does_not_drop_missing_exit_inside_covered_dates():
    frame = pd.DataFrame({
        'trade_date': pd.to_datetime(['2026-07-15']),
        'exit_date': pd.to_datetime(['2026-07-16']),
        'instrument': ['A'],
        'exit_1000': [float('nan')],
    })
    kept, excluded = restrict_to_complete_exit_horizon(frame, pd.Timestamp('2026-07-16'))
    assert excluded == []
    assert len(kept) == 1
    assert kept['exit_1000'].isna().all()
