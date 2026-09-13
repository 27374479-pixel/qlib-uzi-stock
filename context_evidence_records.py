"""Evidence-bound assistant annotations; NOT an automatic theme classifier."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path('output/local_event_rebuild_20260911/context_v2/body_pilot')


def bind_claim(body, field, value, quote):
    normalized = re.sub(r'\s+', '', body)
    normalized_quote = re.sub(r'\s+', '', quote)
    if not normalized_quote:
        raise ValueError('empty evidence')
    start = normalized.find(normalized_quote)
    if start < 0:
        raise ValueError('evidence not found in source')
    return dict(field=field, value=value, quote=quote,
                normalized_start=start, normalized_end=start+len(normalized_quote),
                offset_basis='source text with whitespace removed',
                semantic_review='assistant annotated; exact-span check does not prove interpretation')


def main():
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    specifications = {
        '9366dbd2a7c3': [
            ('transaction_target', '中兴能源装备有限公司100%股权', '中兴能源装备有限公司100%股权'),
            ('transaction_status', 'NO_BIDDER_NOT_COMPLETED', '在公告期内无意向受让方报名申购'),
            ('next_step', 'RELISTING_REQUIRES_BOARD_REVIEW', '公司将另行召开董事会审议重新公开挂牌转让标的资产相关事宜'),
        ],
        'b4055df9e9a4': [
            ('product', '依折麦布片', '药品通用名称：依折麦布片'),
            ('authorization_holder', '云南龙津康佑生物医药有限公司', '上市许可持有人：云南龙津康佑生物医药有限公司'),
            ('event_status', 'REGISTRATION_RECEIVED', '收到国家药品监督管理局核准签发的依折麦布片《药品注册证书》'),
            ('impact_qualification', 'NO_MATERIAL_2025_IMPACT_EXPECTED', '预计对公司2025年经营业绩不会产生重大影响'),
        ],
    }
    output = []
    for prefix, claims in specifications.items():
        rows = [r for r in manifest['records'] if r['event_id'].startswith(prefix)]
        if len(rows) != 1:
            raise ValueError('nonunique source identity')
        row = rows[0]
        raw = Path(row['body_path']).read_bytes()
        # Pilot hash covers logical text before Windows newline translation.
        body = Path(row['body_path']).read_text(encoding='utf-8')
        if hashlib.sha256(body.encode('utf-8')).hexdigest() != row['body_sha256']:
            raise ValueError('body hash mismatch')
        output.append(dict(event_id=row['event_id'], source_url=row['source_url'],
                           body_file_sha256=hashlib.sha256(raw).hexdigest(),
                           body_sha256=row['body_sha256'], published_date=row['published_date'],
                           claims=[bind_claim(body, *claim) for claim in claims],
                           theme_id=None, price_direction=None, backtest_use_allowed=False,
                           historical_version_verified=False))
    (ROOT / 'structured_evidence.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(output)} documents; {sum(len(r["claims"]) for r in output)} source-bound claims; no performance use')


if __name__ == '__main__':
    main()
