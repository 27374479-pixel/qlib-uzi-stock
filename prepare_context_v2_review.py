"""Streaming, market-blind coverage audit and deterministic body-review queue."""
import hashlib
import heapq
import json
from collections import Counter
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq
from event_context_candidate_v2 import route_title, VERSION

ROOT = Path('data_lake/local_rebuild_20260911/notices')
OUT = Path('output/local_event_rebuild_20260911/context_v2')
FIELDS = ['event_id', 'instrument', 'title', 'published_date', 'source_url']


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    counts, heaps = {}, {}
    for path in sorted(ROOT.glob('year=*/notices_*.parquet')):
        year = path.parent.name.split('=')[1]
        count, heap = Counter(), []
        for batch in pq.ParquetFile(path).iter_batches(batch_size=20000, columns=FIELDS):
            for row in batch.to_pylist():
                route = route_title(row['title'])
                count[route['routing_status']] += 1
                if route['routing_status'] != 'BODY_REVIEW_REQUIRED':
                    continue
                record = dict(row, **route)
                rank = int(hashlib.sha256(row['event_id'].encode()).hexdigest(), 16)
                item = (-rank, row['event_id'], record)
                if len(heap) < 100:
                    heapq.heappush(heap, item)
                elif item[:2] > heap[0][:2]:
                    heapq.heapreplace(heap, item)
        counts[year], heaps[year] = dict(count), heap
        print(year, dict(count), flush=True)
    rows = [item[2] for heap in heaps.values() for item in heap]
    pd.DataFrame(rows).sort_values(['published_date', 'event_id']).to_csv(OUT / 'body_review_queue.csv', index=False)
    report = dict(version=VERSION, status='CANDIDATE_NOT_CALIBRATED',
                  market_returns_read=False, source_fields=FIELDS,
                  years=counts, review_queue_rows=len(rows),
                  theme_assignment_allowed=False,
                  rule_sha256=hashlib.sha256(Path('event_context_candidate_v2.py').read_bytes()).hexdigest(),
                  limitations=['Action categories are not shared themes.',
                               'Routine routing is a candidate heuristic, not a deletion rule.',
                               'Original notices remain unchanged.',
                               'New text QA required; previous audit is development evidence, not holdout.'])
    (OUT / 'routing_manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
