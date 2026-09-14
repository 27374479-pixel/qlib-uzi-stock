from __future__ import annotations
import json
from pathlib import Path
from x02_provenance import sha256_file

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/"V5_W08_LEADER_IDENTITY_SOURCE_REVIEW.md"
W01=ROOT/"V5_W01_BEAR_PULLBACK_SOURCE_REVIEW.md"
OUT=ROOT/"output"/"v5_w08_leader_identity_source_readiness"
REPORT=OUT/"report.json"
FIELDS=("leader_scope","identity_observables","trait_precedence","theme_relation","identity_start","identity_persistence","tie_policy","handoff_policy","accessibility_policy","independent_validation","causal_lineage","w01_binding")


def evidence():
    return {
        "leader_scope":False,
        "identity_observables":False,
        "trait_precedence":False,
        "theme_relation":False,
        "identity_start":False,
        "identity_persistence":False,
        "tie_policy":False,
        "handoff_policy":False,
        "accessibility_policy":False,
        "independent_validation":False,
        "causal_lineage":True,
        "w01_binding":True,
    }


def evaluate(e):
    missing=[k for k in FIELDS if k not in e]
    unresolved=[k for k in FIELDS if k in e and not bool(e[k])]
    ready=not missing and not unresolved
    return {"status":"READY_FOR_LEADER_IDENTITY_PREREGISTRATION" if ready else "DEFER_LEADER_IDENTITY_PREREGISTRATION","ready":ready,"missing":missing,"unresolved":unresolved,"next_action":"WRITE_SEPARATE_PREREGISTRATION" if ready else "SOURCE_AND_REPRESENTATION_RESEARCH_ONLY"}


def run():
    for p in (SOURCE,W01):
        if not p.exists(): raise FileNotFoundError(p)
    report={"version":"V5_W08_LEADER_IDENTITY_SOURCE_READINESS_V1","parameter_search":False,"source_sha256":sha256_file(SOURCE),"w01_sha256":sha256_file(W01),"evidence":evidence()}
    report["decision"]=evaluate(report["evidence"])
    OUT.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return report

if __name__=="__main__": run()
