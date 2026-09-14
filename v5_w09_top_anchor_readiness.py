from __future__ import annotations

import json
from pathlib import Path

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
REVIEW = ROOT / "V5_W09_TOP_ANCHOR_SOURCE_REVIEW.md"
W08_RESULT = ROOT / "V5_W08_RESULT.md"
OUT = ROOT / "output" / "v5_w09_top_anchor_readiness"
REPORT = OUT / "report.json"

REQUIRED = (
    "leader_identity_prerequisite",
    "price_adjustment_basis",
    "anchor_price_field",
    "candidate_top_rule",
    "confirmation_rule",
    "confirmation_delay",
    "known_time",
    "new_high_reset_rule",
    "drawdown_measurement_basis",
    "three_to_seven_session_clock",
    "first_event_interaction",
    "independent_validation_target_or_source_basis",
    "w08_lineage_binding",
)


def evidence():
    return {
        "leader_identity_prerequisite": {"ready": False, "detail": "W08 validates descriptive leader evidence only; no total-leader label is authorized"},
        "price_adjustment_basis": {"ready": False, "detail": "source does not specify raw/adjusted corporate-action treatment"},
        "anchor_price_field": {"ready": False, "detail": "source says post-top but does not specify intraday high, close or another price field"},
        "candidate_top_rule": {"ready": False, "detail": "no causal candidate-top rule is supplied"},
        "confirmation_rule": {"ready": False, "detail": "retrospective swing-top confirmation is not machine-defined by the source"},
        "confirmation_delay": {"ready": False, "detail": "number/timing of completed observations required to confirm a top is unspecified"},
        "known_time": {"ready": False, "detail": "earliest timestamp at which a confirmed top may affect an order is unspecified"},
        "new_high_reset_rule": {"ready": False, "detail": "source does not define how a later new high invalidates or resets the top anchor"},
        "drawdown_measurement_basis": {"ready": False, "detail": "source gives ~20%-25% decline but not exact top/current price fields"},
        "three_to_seven_session_clock": {"ready": False, "detail": "source gives 3-7 trading sessions but not the exact clock-start convention"},
        "first_event_interaction": {"ready": False, "detail": "the first-opportunity requirement exists but its exact interaction with top confirmation/reset is unresolved"},
        "independent_validation_target_or_source_basis": {"ready": False, "detail": "no non-P&L target fixes the discretionary top semantics"},
        "w08_lineage_binding": {"ready": True, "detail": "W09 binds the frozen W08 result"},
    }


def evaluate(e):
    missing = [k for k in REQUIRED if k not in e]
    not_ready = [k for k in REQUIRED if k in e and not bool(e[k].get("ready"))]
    ready = not missing and not not_ready
    return {
        "status": "READY_FOR_TOP_ANCHOR_PREREGISTRATION" if ready else "DEFER_TOP_ANCHOR_PREREGISTRATION",
        "ready": ready,
        "missing_fields": missing,
        "not_ready_fields": not_ready,
        "top_anchor_preregistration_authorized": ready,
        "w01_return_screen_authorized": False,
        "effective_action": "WRITE_SEPARATE_TOP_ANCHOR_PREREGISTRATION" if ready else "SOURCE_AND_CAUSAL_TOP_REPRESENTATION_ONLY",
        "x02_change_authorized": False,
        "portfolio_combination_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run():
    for path in (REVIEW, W08_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)
    report = {
        "version": "V5_W09_TOP_ANCHOR_READINESS_V1",
        "parameter_search": False,
        "lineage": {
            "review_sha256": sha256_file(REVIEW),
            "w08_result_sha256": sha256_file(W08_RESULT),
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
