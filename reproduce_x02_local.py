"""Reproduce existing X02 specification; no announcement or parameter search."""
import json
import hashlib
from pathlib import Path
import pandas as pd
import v4_3_long_only_portfolio as engine

OUT = Path('output/x02_reproduction_20260912')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    contract = dict(signal='existing X02', top_n=3, rank='clean_mom20_rank',
                    entry='14:45 close', exit='next session 10:00', limit_buffer=.005,
                    variants=['original_gate', 'no_market_gate'], costs=['BASE', 'CONSERVATIVE'],
                    purpose='historical reproduction and single-factor gate ablation, not pristine OOS',
                    parameter_search=False, announcements_used=False)
    (OUT / 'contract.json').write_text(json.dumps(contract, indent=2), encoding='utf-8')
    print('Preparing existing daily candidates', flush=True)
    candidates, dates = engine._prepare_candidates()
    print(f'Candidates: {len(candidates)}; extracting persisted minutes', flush=True)
    minute = engine._minute_extract(candidates)
    features = engine._add_intraday_features(candidates, minute)
    features.to_parquet(OUT / 'features.parquet', index=False)
    executable = features[features.base_executable]
    if executable.empty:
        raise RuntimeError('No executable coverage')
    dates = [d for d in dates if executable.trade_date.min() <= d <= executable.trade_date.max()]
    coverage = dict(candidate_rows=len(candidates), minute_matches=len(minute),
                    executable_rows=len(executable), first=str(min(dates)), last=str(max(dates)))
    reports = {}
    for variant in contract['variants']:
        eligible = features[features.base_executable & features.limit_gap.ge(.005)].copy()
        if variant == 'original_gate':
            eligible = eligible[eligible.breadth5.fillna(-1).gt(0) & eligible.money_effect.fillna(-1).gt(0)].copy()
        eligible['score'] = eligible.clean_mom20_rank.fillna(float('-inf'))
        selected = engine._select_top(eligible, 3)
        for cost in contract['costs']:
            series, ledger = engine._portfolio_series(selected, dates, '10:00', cost)
            key = f'{variant}_{cost}'
            ledger.to_csv(OUT / f'{key}_ledger.csv', index=False)
            series.rename('net_return').to_csv(OUT / f'{key}_daily.csv')
            periods = dict(all=(None, None), development=(None,pd.Timestamp('2023-12-31')),
                           later=(pd.Timestamp('2024-01-01'),None))
            reports[key] = {name:engine._metrics(*engine._slice(series,ledger,*window)) for name,window in periods.items()}
    report = dict(contract=contract, coverage=coverage, results=reports,
                  engine_sha256=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
                  limitations=['Reproduces legacy execution assumptions; not live-trading certification.',
                               '14:45 close fill and missing-exit handling require separate execution audit.',
                               'Previously inspected later period is not pristine OOS.'])
    (OUT / 'report.json').write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, indent=2, default=str), flush=True)


if __name__ == '__main__':
    main()
