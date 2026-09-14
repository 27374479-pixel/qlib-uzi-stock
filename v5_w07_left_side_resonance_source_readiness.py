"""Fail-closed W07 readiness gate for market/stock left-side resonance."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from x02_provenance import sha256_file

ROOT=Path(__file__).resolve().parent
SOURCE_REVIEW=ROOT/'V5_W07_LEFT_SIDE_RESONANCE_SOURCE_REVIEW.md'
W06_RESULT=ROOT/'V5_W06_RESULT.md'
W05_RESULT=ROOT/'V5_W05_RESULT.md'
W04_RESULT=ROOT/'V5_W04_RESULT.md'
W03_RESULT=ROOT/'V5_W03_RESULT.md'
W02_RESULT=ROOT/'V5_W02_RESULT.md'
M02_RESULT=ROOT/'V5_M02_RESULT.md'
OUT=ROOT/'output'/'v5_w07_left_side_resonance_source_readiness'
REPORT=OUT/'report.json'

REQUIRED=(
 'market_reference_series','market_left_side_state','stock_left_side_state','resonance_operator',
 'synchronization_tolerance','critical_point_definition','causal_known_time','entry_execution_time',
 'mismatch_policy','independent_validation_or_source_basis','upstream_lineage_binding')

CONTRACT={
 'version':'V5_W07_LEFT_SIDE_RESONANCE_SOURCE_READINESS_V1','mode':'SOURCE_READINESS_ONLY',
 'source_fixed':{'market_stock_resonance_required':True,'waiting_is_part_of_method':True,'critical_point_named_but_not_numeric':True},
 'parameter_search':False,'resonance_preregistration_authorized':False,'w01_event_preregistration_authorized':False,
 'w01_return_screen_authorized':False,'x02_change_authorized':False,'portfolio_combination_authorized':False,
 'paper_trading_authorized':False,'live_trading_authorized':False}

def evidence()->dict[str,dict[str,Any]]:
    unresolved={
      'market_reference_series':'source says broad market but does not identify one exact point-in-time series/universe',
      'market_left_side_state':'source does not machine-define broad-market left-side state',
      'stock_left_side_state':'source does not machine-define the stock left-side state beyond qualitative setup language',
      'resonance_operator':'source requires resonance but does not give an AND/transition/state-pair function',
      'synchronization_tolerance':'source does not specify same-session or lagged-session tolerance',
      'critical_point_definition':'source names a critical intervention point but gives no deterministic price/state predicate',
      'causal_known_time':'earliest timestamp when both market and stock states are known is unspecified',
      'entry_execution_time':'first executable timestamp after the decision is unspecified',
      'mismatch_policy':'source does not explicitly define handling of contradictory market/stock states',
      'independent_validation_or_source_basis':'no non-P&L basis currently resolves the state and synchronization choices'}
    out={k:{'ready':False,'detail':v} for k,v in unresolved.items()}
    out['upstream_lineage_binding']={'ready':True,'detail':'W07 binds frozen M02 and W02-W06 results plus its source review'}
    out['literal_market_stock_resonance']={'ready':True,'detail':'source explicitly says to wait for broad-market and stock left-side resonance'}
    out['literal_waiting_and_critical_point']={'ready':True,'detail':'source emphasizes waiting and intervention at a critical point'}
    return out

def evaluate(e):
    missing=[f for f in REQUIRED if f not in e]
    not_ready=[{'field':f,'detail':e[f].get('detail')} for f in REQUIRED if f in e and not bool(e[f].get('ready'))]
    ready=not missing and not not_ready
    return {'status':'READY_FOR_LEFT_SIDE_RESONANCE_PREREGISTRATION' if ready else 'DEFER_LEFT_SIDE_RESONANCE_PREREGISTRATION',
            'ready':ready,'missing_fields':missing,'not_ready':not_ready,'resonance_preregistration_authorized':ready,
            'w01_event_preregistration_authorized':False,'w01_return_screen_authorized':False,
            'effective_action':'WRITE_SEPARATE_LEFT_SIDE_RESONANCE_PREREGISTRATION' if ready else 'SOURCE_AND_REPRESENTATION_RESEARCH_ONLY',
            'x02_change_authorized':False,'portfolio_combination_authorized':False,'paper_trading_authorized':False,'live_trading_authorized':False}

def run():
    for p in (SOURCE_REVIEW,W06_RESULT,W05_RESULT,W04_RESULT,W03_RESULT,W02_RESULT,M02_RESULT):
        if not p.exists(): raise FileNotFoundError(p)
    report={'contract':CONTRACT,'lineage':{'source_review_sha256':sha256_file(SOURCE_REVIEW),'w06_result_sha256':sha256_file(W06_RESULT),'w05_result_sha256':sha256_file(W05_RESULT),'m02_result_sha256':sha256_file(M02_RESULT)},'evidence':evidence()}
    report['decision']=evaluate(report['evidence'])
    report['interpretation_boundary']='W07 preserves the book requirement for market/stock left-side resonance but refuses to invent state definitions or synchronization from strategy P&L.'
    OUT.mkdir(parents=True,exist_ok=True); REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2)); return report

if __name__=='__main__': run()
