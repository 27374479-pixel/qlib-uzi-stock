"""Post-reproduction accounting diagnostics; no parameter selection."""
import json
from pathlib import Path
import pandas as pd
import v4_3_long_only_portfolio as engine

OUT = Path('output/x02_reproduction_20260912')


def main():
    report = json.loads((OUT / 'report.json').read_text())
    features = pd.read_parquet(OUT / 'features.parquet')
    rows, missing = [], []
    for variant in ['original_gate', 'no_market_gate']:
        y = features[features.base_executable & features.limit_gap.ge(.005)].copy()
        if variant == 'original_gate':
            y = y[y.breadth5.fillna(-1).gt(0) & y.money_effect.fillna(-1).gt(0)].copy()
        y['score'] = y.clean_mom20_rank.fillna(float('-inf'))
        selected = engine._select_top(y, 3)
        for year, group in selected.groupby(selected.trade_date.dt.year):
            missing.append(dict(variant=variant, year=int(year), selected=len(group),
                                missing_exit=int(group.exit_1000.isna().sum()),
                                selection_dates=int(group.trade_date.nunique())))
        for cost in ['BASE', 'CONSERVATIVE']:
            daily = pd.read_csv(OUT / f'{variant}_{cost}_daily.csv', index_col=0, parse_dates=True).iloc[:,0]
            ledger = pd.read_csv(OUT / f'{variant}_{cost}_ledger.csv', parse_dates=['trade_date'])
            for year, s in daily.groupby(daily.index.year):
                z = ledger[ledger.trade_date.dt.year.eq(year)]
                m = engine._metrics(s, z)
                # Include starting cash in peak; legacy metrics omit it.
                wealth = (1+s).cumprod()
                corrected_mdd = float((wealth / wealth.cummax().clip(lower=1) - 1).min())
                rows.append(dict(variant=variant,cost=cost,year=int(year),
                                 return_total=m['total_return'],max_drawdown=corrected_mdd,
                                 active_days=m['active_days'],trade_rows=len(z),days=len(s)))
    pd.DataFrame(rows).to_csv(OUT / 'annual_diagnostics.csv', index=False)
    comparison = {}
    oldpath = Path('output/v4_14_book_h12_h20_capacity_concentration.json')
    if oldpath.exists():
        old = json.loads(oldpath.read_text(encoding='utf-8'))['H20']['concentration_results']['3']
        for cost in ['BASE','CONSERVATIVE']:
            comparison[cost] = {new:report['results'][f'original_gate_{cost}'][new]['cagr']-old[cost][previous]['cagr']
                                for new, previous in [('all','all'),('development','development_2021_2023'),('later','oos_2024_2026')]}
    result = dict(missing_exit_by_year=missing, cagr_delta_from_previous=comparison,
                  note='Missing exits are omitted by legacy engine; this diagnostic does not approve that behavior.')
    (OUT / 'diagnostics.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(pd.DataFrame(rows).to_string(index=False))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
