"""Persist explicit partial assistant title review; never reads market outcomes.

Only rows 280..319 were reviewed. Unreviewed rows remain blank. This is not
an independent human audit and must not be represented as complete calibration.
"""
import hashlib
import json
from pathlib import Path
import pandas as pd

ROOT = Path('output/local_event_rebuild_20260911')
source = ROOT / 'text_pairs.csv'
assert hashlib.sha256(source.read_bytes()).hexdigest() == 'eeb12c71420a04ea3ee6da4806dca624ce7de464125f7365f431576026223043'
pairs = pd.read_csv(source).fillna('')
ambiguous = {281, 284, 297, 304, 317}
for i in range(280, 320):
    assert float(pairs.at[i, 'similarity']) >= .85
    assert pairs.at[i, 'instrument_a'] != pairs.at[i, 'instrument_b']
    pairs.at[i, 'pair_label'] = 'AMBIGUOUS' if i in ambiguous else 'DIFFERENT_CONTEXT'
    pairs.at[i, 'review_note'] = (
        'Assistant text-only review: title omits substantive economic details; shared context cannot be determined.'
        if i in ambiguous else
        'Assistant text-only review: unrelated issuers share a routine filing template; not evidence of one economic theme.'
    )
pairs.to_csv(ROOT / 'text_pairs_partial_review.csv', index=False)
# Every preregistered threshold <= .70 predicts these 35 reviewed negatives
# positive. Even if ALL remaining pairs were true positives, precision cannot
# exceed (320 - 35) / 320. Excluding ambiguous/unreviewed rows cannot raise this
# optimistic bound, since all confirmed negatives remain predicted positive.
negative_count = 40 - len(ambiguous)
bound = (len(pairs) - negative_count) / len(pairs)
report = dict(
    status='TEXT_REPRESENTATION_REQUIRES_REVISION',
    reviewer='assistant; partial title-only review, not independent human QA',
    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    reviewed_pairs=40, different_context=negative_count, ambiguous=len(ambiguous),
    unreviewed_pairs=280, threshold_grid=[.30,.35,.40,.45,.50,.55,.60,.65,.70],
    optimistic_precision_upper_bound=bound, required_precision=.90,
    explanation='All 35 confirmed negatives have similarity >= .85, above every frozen candidate threshold. Even granting every other pair true-positive status cannot attain .90 precision on this audit set.',
    returns_read=False, formal_backtest_run=False,
)
(ROOT / 'text_review_diagnostic.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
