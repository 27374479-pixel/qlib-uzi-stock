"""Fixed two-per-year body retrieval pilot; not historical-version approval."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests

OUT = Path('output/local_event_rebuild_20260911/context_v2/body_pilot')
ENDPOINT = 'https://np-cnotice-stock.eastmoney.com/api/content/ann'


def validate_page(payload, art_code, published_date):
    data = payload.get('data', {})
    if data.get('art_code') != art_code:
        raise ValueError('announcement identity mismatch')
    if str(data.get('notice_date', ''))[:10] != published_date:
        raise ValueError('publication date mismatch')
    if not isinstance(data.get('notice_content'), str) or not data['notice_content'].strip():
        raise ValueError('missing body text')
    pages = int(data.get('page_size', 0))
    if not 1 <= pages <= 100:
        raise ValueError('unexpected page count')
    return data, pages


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    queue_path = OUT.parent / 'body_review_queue.csv'
    queue = pd.read_csv(queue_path, dtype=str)
    queue['year'] = queue.published_date.str[:4]
    sample = queue.sort_values(['published_date', 'event_id']).groupby('year', sort=True).head(2)
    results = []
    for row in sample.to_dict('records'):
        record = dict(row, historical_version_verified=False, backtest_use_allowed=False)
        try:
            art_code = re.search(r'/([^/]+)\.html$', row['source_url']).group(1)
            pages, texts, evidence = 1, [], []
            index = 1
            while index <= pages:
                response = requests.get(ENDPOINT, params=dict(art_code=art_code, client_source='web', page_index=index), timeout=25)
                response.raise_for_status()
                raw_hash = hashlib.sha256(response.content).hexdigest()
                raw_path = OUT / f'{raw_hash}.json'
                if not raw_path.exists():
                    raw_path.write_bytes(response.content)
                data, observed_pages = validate_page(response.json(), art_code, row['published_date'])
                if index > 1 and observed_pages != pages:
                    raise ValueError('page count changed during retrieval')
                pages = observed_pages
                texts.append(data['notice_content'])
                evidence.append(dict(page=index, raw_sha256=raw_hash, raw_path=str(raw_path),
                                     retrieved_at=datetime.now(timezone.utc).isoformat(), url=response.url))
                index += 1
            body = '\n'.join(texts)
            body_path = OUT / f"{row['event_id']}.txt"
            body_path.write_text(body, encoding='utf-8')
            quality = 'BODY_INCOMPLETE_REQUIRES_ATTACHMENT' if len(body.strip()) < 100 else 'BODY_RETRIEVED_NOT_PIT_APPROVED'
            record.update(status=quality, pages=pages, characters=len(body),
                          body_path=str(body_path), body_sha256=hashlib.sha256(body.encode()).hexdigest(),
                          evidence=evidence, original_attachment_url=data.get('attach_url_web'),
                          provider_title=data.get('notice_title'))
        except Exception as exc:
            record.update(status='FAILED', error=str(exc))
        results.append(record)
        print(row['event_id'][:12], record['status'], flush=True)
        (OUT / 'manifest.json').write_text(json.dumps(dict(
            status='PILOT_NOT_CALIBRATED', selection='first two by publication date/event ID per year from frozen queue',
            queue_sha256=hashlib.sha256(queue_path.read_bytes()).hexdigest(),
            endpoint_discovery='https://data.eastmoney.com/newstatic/js/notices/detail_a.js',
            returns_read=False, records=results), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
