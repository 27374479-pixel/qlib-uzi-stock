"""Recover failed pilot bodies without changing the original pilot manifest."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from pypdf import PdfReader

ROOT = Path('output/local_event_rebuild_20260911/context_v2/body_pilot')


def main():
    out = ROOT / 'attachment_recovery'
    out.mkdir(exist_ok=True)
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    results = []
    for row in manifest['records']:
        if row['status'] == 'BODY_RETRIEVED_NOT_PIT_APPROVED':
            continue
        result = dict(event_id=row['event_id'], backtest_use_allowed=False,
                      historical_version_verified=False)
        try:
            art = re.search(r'(AN\d+)', row['source_url']).group(1)
            response = requests.get('https://np-cnotice-stock.eastmoney.com/api/content/ann', params=dict(art_code=art, client_source='web', page_index=1), timeout=25)
            response.raise_for_status()
            data = response.json()['data']
            if data['art_code'] != art or data['notice_date'][:10] != row['published_date']:
                raise ValueError('identity/date mismatch')
            url = data['attach_url_web']
            if urlparse(url).hostname != 'pdf.dfcfw.com' or art not in url:
                raise ValueError('unexpected attachment identity/host')
            metadata_hash = hashlib.sha256(response.content).hexdigest()
            (out / f'{metadata_hash}.json').write_bytes(response.content)
            pdf = requests.get(url, timeout=60)
            pdf.raise_for_status()
            if not pdf.content.startswith(b'%PDF-'):
                raise ValueError('attachment is not PDF')
            digest = hashlib.sha256(pdf.content).hexdigest()
            path = out / f'{digest}.pdf'
            path.write_bytes(pdf.content)
            reader = PdfReader(path)
            pages = [page.extract_text() or '' for page in reader.pages]
            text_path = out / f'{digest}.txt'
            text_path.write_text('\n\f\n'.join(pages), encoding='utf-8')
            result.update(status='EXTRACTED_REQUIRES_QA', attachment_url=url,
                          retrieved_at=datetime.now(timezone.utc).isoformat(),
                          pdf_path=str(path), pdf_sha256=digest, text_path=str(text_path),
                          metadata_sha256=metadata_hash, pages=len(pages),
                          empty_pages=[i+1 for i, text in enumerate(pages) if not text.strip()],
                          characters=sum(map(len,pages)))
        except Exception as exc:
            result.update(status='FAILED', error=str(exc))
        results.append(result)
        print(json.dumps(result, ensure_ascii=True), flush=True)
    (out / 'manifest.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
