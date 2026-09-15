"""Fail-closed M06 source-readiness gate for bear-market recovery transitions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_M06_RECOVERY_TRANSITION_SOURCE_REVIEW.md"
M01_RESULT = ROOT / "V5_M01_RESULT.md"
M04_RESULT = ROOT / "V5_M04_RESULT.md"
M05_RESULT = ROOT / "V5_M05_RESULT.md"
OUT = ROOT / "output" / "v5_m06_recovery_transition_readiness"
REPORT = OUT / "report.json"

REQUIRED = (
    "prior_bear_state_requirement",
    "settling_observable_set",
    "recovery_observable_set",
    "necessary_vs_optional_logic",
    "boundary_basis",
    "persistence_rule",
    "transition_reset_rule",
    "conflict_and_ambiguity_policy",
    "cross_industry_broadening_role",
    "decision_known_time",
    "first_effective_trading_time",
    "independent_validation_target",
    "m01_m04_m05_lineage_binding",
)

CONTRACT = {
    "version": "V5_M06_RECOVERY_TRANSITION_READINESS_V1",
    "mode": "SOURCE_READINESS_ONLY",
    "source_fixed": {
        "market_is_cyclical": True,
        "large_prior_decline_is_not_sufficient": True,
        "decline_settling_precedes_recovery": True,
        "new_strong_stock_opportunity_may_follow_recovery": True,
    },
    "parameter_search": False,
    "recovery_transition_preregistration_authorized": False,
    "return_screen_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def evidence() -> dict[str, dict[str, Any]]:
    return {
        "prior_bear_state_requirement": {"ready": False, "detail": "source implies a prior bear decline but gives no machine-ready bear-state requirement or duration"},
        "settling_observable_set": {"ready": False, "detail": "source says decline settles but does not specify which frozen tape dimensions must show settling"},
        "recovery_observable_set": {"ready": False, "detail": "source says recovery begins but does not define the required frozen M01/M04/M05 recovery dimensions"},
        "necessary_vs_optional_logic": {"ready": False, "detail": "source does not define AND/OR precedence across breadth, limit activity, prior-winner treatment and dispersion"},
        "boundary_basis": {"ready": False, "detail": "no numeric boundaries are supplied for a recovery transition"},
        "persistence_rule": {"ready": False, "detail": "source does not say how many completed sessions of improvement are required"},
        "transition_reset_rule": {"ready": False, "detail": "source does not define reset after renewed deterioration or failed recovery"},
        "conflict_and_ambiguity_policy": {"ready": False, "detail": "source does not say what to do when recovery dimensions disagree"},
        "cross_industry_broadening_role": {"ready": False, "detail": "M04 measures broadening, but source does not make a machine-ready broadening condition necessary for bear recovery"},
        "decision_known_time": {"ready": False, "detail": "semantic transition is not timestamped relative to completed close"},
        "first_effective_trading_time": {"ready": False, "detail": "earliest session on which a recovery label may affect orders is unspecified"},
        "independent_validation_target": {"ready": False, "detail": "no noncircular label/target exists yet to falsify the transition independently of strategy returns"},
        "m01_m04_m05_lineage_binding": {"ready": True, "detail": "current branch can bind frozen M01/M04/M05 result hashes"},
        "source_cycle_sequence": {"ready": True, "detail": "source supports deterioration -> settling -> recovery as a qualitative ordering"},
        "source_large_decline_guard": {"ready": True, "detail": "source explicitly warns that prior decline alone is not enough"},
    }


def evaluate(e: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [field for field in REQUIRED if field not in e]
    not_ready = [
        {"field": field, "detail": e[field].get("detail")}
        for field in REQUIRED
        if field in e and not bool(e[field].get("ready"))
    ]
    ready = not missing and not not_ready
    return {
        "status": "READY_FOR_BEAR_RECOVERY_TRANSITION_PREREGISTRATION" if ready else "DEFER_BEAR_RECOVERY_TRANSITION_PREREGISTRATION",
        "ready": ready,
        "missing_fields": missing,
        "not_ready": not_ready,
        "recovery_transition_preregistration_authorized": ready,
        "return_screen_authorized": False,
        "w01_return_screen_authorized": False,
        "effective_action": "WRITE_SEPARATE_RECOVERY_TRANSITION_PREREGISTRATION" if ready else "SOURCE_AND_INDEPENDENT_STATE_VALIDATION_ONLY",
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    for path in (SOURCE_REVIEW, M01_RESULT, M04_RESULT, M05_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)
    report = {
        "contract": CONTRACT,
        "lineage": {
            "source_review_sha256": sha256_file(SOURCE_REVIEW),
            "m01_result_sha256": sha256_file(M01_RESULT),
            "m04_result_sha256": sha256_file(M04_RESULT),
            "m05_result_sha256": sha256_file(M05_RESULT),
        },
        "evidence": evidence(),
    }
    report["decision"] = evaluate(report["evidence"])
    report["interpretation_boundary"] = (
        "M06 preserves the source ordering of deterioration, settling and recovery while refusing to invent a tradable transition from historical strategy returns."
    )
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
