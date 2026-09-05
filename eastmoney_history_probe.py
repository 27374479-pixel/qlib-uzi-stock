from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import requests

OUT = Path('output/eastmoney_history_probe.json')
OUT.parent.mkdir(exist_ok=True)

symbol = '1.600295'
url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
common = {
    'secid': symbol,
    'klt': '5',
    'fqt': '0',
    'fields1': 'f1,f2,f3,f4,f5,f6',
    'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
}
variants = [
    ('plain_range_lmt', {'beg':'20250102','end':'20260903','lmt':'1000000'}),
    ('ut_fa_range_lmt', {'beg':'20250102','end':'20260903','lmt':'1000000','ut':'fa5fd1943c7b386f172d6893dbbd1d0c'}),
    ('ut_7ee_range', {'beg':'20250102','end':'20260903','ut':'7eea3edcaed734bea9cbfc24409ed989'}),
    ('ut_7ee_from_zero_lmt', {'beg':'0','end':'20260903','lmt':'1000000','ut':'7eea3edcaed734bea9cbfc24409ed989'}),
]

s = requests.Session()
s.headers.update({
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36',
    'Referer':'https://quote.eastmoney.com/',
    'Accept':'application/json,text/plain,*/*',
})
results=[]
for i,(name,extra) in enumerate(variants):
    if i:
        time.sleep(30)
    params={**common, **extra}
    rec={'name':name,'params':extra}
    try:
        r=s.get(url,params=params,timeout=20)
        rec['http_status']=r.status_code
        r.raise_for_status()
        payload=r.json()
        ks=((payload.get('data') or {}).get('klines') or [])
        dts=[]
        for x in ks:
            p=str(x).split(',')
            if p:
                dt=pd.to_datetime(p[0],errors='coerce')
                if pd.notna(dt): dts.append(dt)
        rec.update({
            'rc':payload.get('rc'),
            'bars':len(dts),
            'min_datetime':str(min(dts)) if dts else None,
            'max_datetime':str(max(dts)) if dts else None,
            'has_2025':any(x.year==2025 for x in dts),
            'has_jan_2025':any(x.year==2025 and x.month==1 for x in dts),
        })
    except Exception as e:
        rec['error']=repr(e)
    results.append(rec)
    print(json.dumps(rec,ensure_ascii=False),flush=True)

OUT.write_text(json.dumps({'symbol':symbol,'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
print('saved',OUT)
