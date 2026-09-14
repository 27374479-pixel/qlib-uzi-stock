"""Source-readiness gate for the U03 replacement-leader idea.

This gate intentionally runs before any return screen.  It encodes whether the
current supplied source is sufficiently unambiguous to preregister a mechanical
replacement-leader signal without inventing missing rules.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_REVIEW = ROOT / "V5_U03_REPLACEMENT_LEADER_SOURCE_REVIEW.md"
OUT = ROOT / "output" / "v5_u03_source_readiness"
REPORT = OUT / "report.json"

REQUIRED_FOR_SIGNAL_PREREGISTRATION = (
    "source_layout_integrity",
    "target_security_definition",
    "leader_target_relationship_definition",
    "recognition_consensus_observable",
    "candidate_ranking_rule",
    "entry_timing_definition",
    "exit_or_horizon_definition",
    "economic_direction_and_control_definition",
)

DEFAULT_EVIDENCE = {
    "leader_ebb_rough_window": {
        "ready": True,
        "detail": "source explicitly contains total-leader ebb of roughly two/three days; context only",
    },
    "source_layout_integrity": {
        "ready": False,
        "detail": "available upper-volume OCR interleaves multiple visual columns",
    },
    "target_security_definition": {
        "ready": False,
        "detail": "follower/replacement target is not machine-defined",
    },
    "leader_target_relationship_definition": {
        "ready": False,
        "detail": "exact same-theme/companion/replacement relationship is not safely recoverable from interleaved OCR",
    },
    "recognition_consensus_observable": {
        "ready": False,
        "detail": "一致性/recognition is named but no point-in-time numeric observable is specified",
    },
    "candidate_ranking_rule": {
        "ready": False,
        "detail": "no source-grounded ranking rule is specified",
    },
    "entry_timing_definition": {
        "ready": False,
        "detail": "no source-grounded daily/minute entry rule is established for U03",
    },
    "exit_or_horizon_definition": {
        "ready": False,
        "detail": "no U03-specific exit or holding horizon is established",
    },
    "economic_direction_and_control_definition": {
        "ready": False,
        "detail": "descriptive replacement-leader wording does not define a return-superiority claim/control",
    },
}

CONTRACT = {
    "version": "V5_U03_SOURCE_READINESS_V1",
    "required_for_signal_preregistration": list(REQUIRED_FOR_SIGNAL_PREREGISTRATION),
    "parameter_search": False,
    "return_screen_authorized": False,
    "signal_preregistration_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def evaluate(evidence: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    missing_fields = [name for name in REQUIRED_FOR_SIGNAL_PREREGISTRATION if name not in evidence]
    not_ready: list[dict[str, str]] = []
    for name in REQUIRED_FOR_SIGNAL_PREREGISTRATION:
        item = evidence.get(name, {})
        if item.get("ready") is not True:
            not_ready.append({"field": name, "detail": str(item.get("detail", "not ready"))})
    ready = not missing_fields and not not_ready
    return {
        "status": "READY_FOR_SIGNAL_PREREGISTRATION" if ready else "DEFER_SIGNAL_PREREGISTRATION",
        "ready": ready,
        "missing_fields": missing_fields,
        "not_ready": not_ready,
        "return_screen_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def run() -> dict[str, Any]:
    if not SOURCE_REVIEW.exists():
        raise FileNotFoundError(SOURCE_REVIEW)
    decision = evaluate(DEFAULT_EVIDENCE)
    payload = {
        "contract": CONTRACT,
        "source_review_sha256": sha256_file(SOURCE_REVIEW),
        "evidence": DEFAULT_EVIDENCE,
        "decision": decision,
        "interpretation_boundary": (
            "U03 source readiness is evaluated before any return data. A DEFER result means better source evidence "
            "is required; it must not be bypassed by trying alternative thresholds on historical outcomes."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


if __name__ == "__main__":
    run()
