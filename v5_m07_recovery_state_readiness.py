from __future__ import annotations

import json
from pathlib import Path

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
REVIEW = ROOT / "V5_M07_RECOVERY_STATE_SOURCE_REVIEW.md"
M06_RESULT = ROOT / "V5_M06_RESULT.md"
M05_RESULT = ROOT / "V5_M05_RESULT.md"
OUT = ROOT / "output" / "v5_m07_recovery_state_readiness"
REPORT = OUT / "report.json"

REQUIRED = (
    "mandatory_dimensions",
    "aggregation_rule",
    "persistence_rule",
    "starting_state_prerequisite",
    "ambiguity_policy",
    "causal_decision_time",
    "independent_validation_target",
    "lineage_binding",
)


def evidence():
    return {
        "mandatory_dimensions": {"ready": False, "detail": "source names several tape dimensions but does not say which are mandatory"},
        "aggregation_rule": {"ready": False, "detail": "no majority/all-of-N/weighted recovery rule is specified"},
        "persistence_rule": {"ready": False, "detail": "source does not define how many completed sessions confirm recovery"},
        "starting_state_prerequisite": {"ready": False, "detail": "bear-context prerequisite is qualitative, not mechanically mapped"},
        "ambiguity_policy": {"ready": False, "detail": "conflicting repair/worsening dimensions have no deterministic resolution"},
        "causal_decision_time": {"ready": False, "detail": "first timestamp at which a recovery state may affect orders is unspecified"},
        "independent_validation_target": {"ready": False, "detail": "no non-strategy-return target is frozen for validating the semantic state"},
        "lineage_binding": {"ready": True, "detail": "M07 can bind frozen M05/M06 results"},
    }


def evaluate(e):
    missing = [k for k in REQUIRED if k not in e]
    not_ready = [k for k in REQUIRED if k in e and not bool(e[k].get("ready"))]
    ready = not missing and not not_ready
    return {
        "status": "READY_FOR_RECOVERY_STATE_PREREGISTRATION" if ready else "DEFER_RECOVERY_STATE_PREREGISTRATION",
        "ready": ready,
        "missing_fields": missing,
        "not_ready_fields": not_ready,
        "state_preregistration_authorized": ready,
        "return_screen_authorized": False,
        "w01_return_screen_authorized": False,
        "effective_action": "WRITE_SEPARATE_STATE_PREREGISTRATION" if ready else "SOURCE_AND_INDEPENDENT_STATE_VALIDATION_ONLY",
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run():
    for path in (REVIEW, M06_RESULT, M05_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)
    report = {
        "version": "V5_M07_RECOVERY_STATE_READINESS_V1",
        "parameter_search": False,
        "lineage": {
            "review_sha256": sha256_file(REVIEW),
            "m06_result_sha256": sha256_file(M06_RESULT),
            "m05_result_sha256": sha256_file(M05_RESULT),
        },
        "evidence": evidence(),
    }
    report["decision"] = evaluate(report["evidence"])
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["decision"], ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
