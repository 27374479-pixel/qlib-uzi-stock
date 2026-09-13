"""Reproduce existing X02 specification; no announcement or parameter search."""
import json
from pathlib import Path

import duckdb
import pandas as pd

import v4_3_long_only_portfolio as engine
from x02_provenance import SELECTION_FILES, sha256_file

OUT = Path('output/x02_reproduction_20260912')


def minute_coverage_end() -> pd.Timestamp:
    """Return the final persisted minute date across the frozen TraderHarness files."""
    missing = [str(path) for path in engine.MINUTE_FILES if not path.exists()]
    if missing:
        raise FileNotFoundError(f'missing persisted minute files: {missing}')
    files_sql = ','.join("'" + str(path.resolve()).replace("'", "''") + "'" for path in engine.MINUTE_FILES)
    con = duckdb.connect()
    try:
        value = con.execute(
            f"SELECT MAX(CAST(datetime AS DATE)) FROM read_parquet([{files_sql}])"
        ).fetchone()[0]
    finally:
        con.close()
    if value is None:
        raise RuntimeError('persisted minute files contain no datetimes')
    return pd.Timestamp(value).normalize()


def restrict_to_complete_exit_horizon(
    features: pd.DataFrame,
    coverage_end: pd.Timestamp,
) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    """Drop whole trade dates whose required exit session is beyond minute coverage.

    This is a data-horizon truncation only: it occurs before ranking/selection and
    never inspects returns. Missing exits *within* the covered horizon remain hard
    failures later so the legacy engine cannot silently reweight surviving rows.
    """
    x = features.copy()
    x['trade_date'] = pd.to_datetime(x['trade_date']).dt.normalize()
    x['exit_date'] = pd.to_datetime(x['exit_date']).dt.normalize()
    cutoff = pd.Timestamp(coverage_end).normalize()
    incomplete_dates = sorted(x.loc[x['exit_date'] > cutoff, 'trade_date'].drop_duplicates())
    if incomplete_dates:
        x = x[~x['trade_date'].isin(incomplete_dates)].copy()
    return x, incomplete_dates


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

    coverage_end = minute_coverage_end()
    features, excluded_trade_dates = restrict_to_complete_exit_horizon(features, coverage_end)
    if excluded_trade_dates:
        print(
            'Excluding whole trade dates beyond persisted exit-data horizon: '
            + ', '.join(str(pd.Timestamp(d).date()) for d in excluded_trade_dates),
            flush=True,
        )
    if features.empty:
        raise RuntimeError('No candidates remain inside complete exit-data horizon')

    features_path = OUT / 'features.parquet'
    features.to_parquet(features_path, index=False)
    executable = features[features.base_executable]
    if executable.empty:
        raise RuntimeError('No executable coverage')
    dates = [d for d in dates if executable.trade_date.min() <= d <= executable.trade_date.max()]
    coverage = dict(
        candidate_rows=len(candidates),
        minute_matches=len(minute),
        candidate_rows_complete_exit_horizon=len(features),
        executable_rows=len(executable),
        minute_coverage_end=str(coverage_end.date()),
        horizon_excluded_trade_dates=[str(pd.Timestamp(d).date()) for d in excluded_trade_dates],
        first=str(min(dates)),
        last=str(max(dates)),
    )
    reports = {}
    selection_artifacts = {}
    for variant in contract['variants']:
        eligible = features[features.base_executable & features.limit_gap.ge(.005)].copy()
        if variant == 'original_gate':
            eligible = eligible[eligible.breadth5.fillna(-1).gt(0) & eligible.money_effect.fillna(-1).gt(0)].copy()
        eligible['score'] = eligible.clean_mom20_rank.fillna(float('-inf'))
        selected = engine._select_top(eligible, 3).copy()
        if selected.empty:
            raise RuntimeError(f'Frozen selection is empty for {variant}')
        counts = selected.groupby('trade_date').instrument.size()
        if not counts.eq(3).all():
            raise RuntimeError(f'Frozen selection does not contain exactly three slots for {variant}')
        missing_exit = selected.exit_1000.isna()
        if bool(missing_exit.any()):
            offenders = selected.loc[missing_exit, ['trade_date', 'instrument']].astype(str).to_dict('records')
            raise RuntimeError(f'Legacy selected rows have missing 10:00 exits for {variant}: {offenders[:10]}')

        selection_path = OUT / SELECTION_FILES[variant]
        selected.to_parquet(selection_path, index=False)
        selection_artifacts[variant] = {
            'filename': selection_path.name,
            'sha256': sha256_file(selection_path),
            'rows': int(len(selected)),
            'active_days': int(selected.trade_date.nunique()),
        }

        for cost in contract['costs']:
            series, ledger = engine._portfolio_series(selected, dates, '10:00', cost)
            if len(ledger) != len(selected):
                raise RuntimeError(f'Legacy portfolio dropped frozen selected rows for {variant}/{cost}')
            key = f'{variant}_{cost}'
            ledger.to_csv(OUT / f'{key}_ledger.csv', index=False)
            series.rename('net_return').to_csv(OUT / f'{key}_daily.csv')
            periods = dict(all=(None, None), development=(None,pd.Timestamp('2023-12-31')),
                           later=(pd.Timestamp('2024-01-01'),None))
            reports[key] = {name:engine._metrics(*engine._slice(series,ledger,*window)) for name,window in periods.items()}
    report = dict(contract=contract, coverage=coverage, results=reports,
                  engine_sha256=sha256_file(Path(engine.__file__)),
                  features_sha256=sha256_file(features_path),
                  selection_artifacts=selection_artifacts,
                  lineage_contract='report.json is valid only with the exact engine/features/selection hashes recorded above',
                  limitations=['Reproduces legacy execution assumptions; not live-trading certification.',
                               '14:45 close fill requires separate next-record execution audit.',
                               'Whole trade dates whose required exit session lies beyond persisted minute coverage are excluded before ranking.',
                               'Selected-row exit coverage inside the retained horizon is a hard requirement to prevent legacy reweighting.',
                               'Previously inspected later period is not pristine OOS.'])
    (OUT / 'report.json').write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, indent=2, default=str), flush=True)


if __name__ == '__main__':
    main()
