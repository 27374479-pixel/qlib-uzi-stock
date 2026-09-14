"""Fail-closed router contract derived from R01 source extraction.

R01 deliberately does not implement a numeric market classifier. This module
only freezes the state schema and authorization boundaries needed for a later
all-weather router without turning discretionary book language into fitted
thresholds.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SOURCE_NOTES = ROOT / "V5_R01_OPPORTUNITY_STATE_SOURCE_NOTES.md"
OUT = ROOT / "output" / "v5_r01_opportunity_router"
STUB = OUT / "current_router_stub.json"

OPPORTUNITY_STATES = ("UNKNOWN", "NO_TRADE", "OPPORTUNITY_PRESENT")
SLEEVE_AUTHORIZATIONS = ("UNAUTHORIZED", "RESEARCH_ONLY", "PAPER_ONLY")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

CONTRACT = {
    "version": "V5_R01_OPPORTUNITY_ROUTER_CONTRACT_V3",
    "source_evidence": ["R01-E1", "R01-E2", "R01-E3", "R01-E4", "R01-E5"],
    "states": list(OPPORTUNITY_STATES),
    "default_state": "UNKNOWN",
    "fail_closed_action": "CASH_ONLY",
    "numeric_regime_classifier_implemented": False,
    "unknown_means_cash": True,
    "no_trade_means_cash": True,
    "opportunity_present_requires_validated_classifier_contract": True,
    "classifier_lineage_requirements": [
        "non-empty contract_id",
        "status == VALIDATED",
        "preregistered == true",
        "lineage_verified == true by the upstream artifact verifier",
        "64-hex classifier_contract_sha256",
        "64-hex validation_artifact_sha256",
    ],
    "sleeve_authorization_requirements": [
        "non-empty evidence_id",
        "non-empty authorization_contract_id",
        "authorization_lineage_verified == true by the upstream artifact verifier",
        "64-hex authorization_artifact_sha256",
    ],
    "router_does_not_self_verify_external_artifact_files": True,
    "sleeves_require_independent_authorization": True,
    "failed_sleeve_rescue_forbidden": True,
    "parameter_search": False,
    "alpha_evaluation_authorized": False,
    "portfolio_optimization_authorized": False,
    "live_trading_authorized": False,
}


def _sha256_hex(value: Any) -> bool:
    return bool(SHA256_RE.fullmatch(str(value or "").strip().lower()))


def sleeve_validation(sleeve: Mapping[str, Any]) -> dict[str, Any]:
    name = str(sleeve.get("name", "")).strip()
    authorization = str(sleeve.get("authorization", "UNAUTHORIZED")).strip().upper()
    reasons: list[str] = []
    if not name:
        reasons.append("sleeve name is missing")
    if authorization not in SLEEVE_AUTHORIZATIONS:
        reasons.append("sleeve authorization is invalid")
        return {"valid": False, "reasons": reasons}
    if authorization == "UNAUTHORIZED":
        return {"valid": not reasons, "reasons": reasons}
    if not str(sleeve.get("evidence_id", "")).strip():
        reasons.append("authorized sleeve evidence_id is missing")
    if not str(sleeve.get("authorization_contract_id", "")).strip():
        reasons.append("authorized sleeve authorization_contract_id is missing")
    if sleeve.get("authorization_lineage_verified") is not True:
        reasons.append("authorized sleeve lineage is not verified")
    if not _sha256_hex(sleeve.get("authorization_artifact_sha256")):
        reasons.append("authorized sleeve artifact SHA-256 is missing or malformed")
    return {"valid": not reasons, "reasons": reasons}


def _normalize_sleeves(sleeves: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sleeve in sleeves or []:
        name = str(sleeve.get("name", "")).strip()
        if not name:
            raise ValueError("sleeve name is required")
        if name in seen:
            raise ValueError(f"duplicate sleeve: {name}")
        authorization = str(sleeve.get("authorization", "UNAUTHORIZED")).strip().upper()
        if authorization not in SLEEVE_AUTHORIZATIONS:
            raise ValueError(f"invalid sleeve authorization for {name}: {authorization}")
        item = dict(sleeve)
        item["name"] = name
        item["authorization"] = authorization
        item["evidence_id"] = str(sleeve.get("evidence_id", "")).strip()
        item["authorization_contract_id"] = str(sleeve.get("authorization_contract_id", "")).strip()
        check = sleeve_validation(item)
        item["authorization_validation"] = check
        seen.add(name)
        normalized.append(item)
    return normalized


def classifier_validation(classifier: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate only the router handoff envelope, not external artifact bytes."""
    reasons: list[str] = []
    if not classifier:
        return {"valid": False, "reasons": ["classifier handoff is missing"]}

    contract_id = str(classifier.get("contract_id", "")).strip()
    status = str(classifier.get("status", "")).strip().upper()
    if not contract_id:
        reasons.append("classifier contract_id is missing")
    if status != "VALIDATED":
        reasons.append("classifier status is not VALIDATED")
    if classifier.get("preregistered") is not True:
        reasons.append("classifier is not marked preregistered")
    if classifier.get("lineage_verified") is not True:
        reasons.append("classifier lineage is not verified")
    if not _sha256_hex(classifier.get("classifier_contract_sha256")):
        reasons.append("classifier contract SHA-256 is missing or malformed")
    if not _sha256_hex(classifier.get("validation_artifact_sha256")):
        reasons.append("classifier validation artifact SHA-256 is missing or malformed")
    return {"valid": not reasons, "reasons": reasons}


def route(
    opportunity_state: str,
    sleeves: Iterable[Mapping[str, Any]] | None = None,
    classifier: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a research routing decision while failing closed to cash.

    Both the market-classifier handoff and every non-UNAUTHORIZED sleeve must be
    artifact-bound by an upstream verifier. R01 checks the envelope and hashes'
    shape; it does not claim to independently open future external files.
    """

    requested_state = str(opportunity_state).strip().upper()
    if requested_state not in OPPORTUNITY_STATES:
        raise ValueError(f"invalid opportunity state: {opportunity_state}")
    normalized = _normalize_sleeves(sleeves)

    classifier_check = classifier_validation(classifier)
    reasons: list[str] = []
    effective_state = requested_state
    if requested_state == "OPPORTUNITY_PRESENT" and not classifier_check["valid"]:
        effective_state = "UNKNOWN"
        reasons.append("opportunity-present request lacks a valid artifact-bound classifier handoff")
        reasons.extend(classifier_check["reasons"])

    invalid_authorized = [
        {
            "name": s["name"],
            "authorization": s["authorization"],
            "reasons": s["authorization_validation"]["reasons"],
        }
        for s in normalized
        if s["authorization"] != "UNAUTHORIZED" and not s["authorization_validation"]["valid"]
    ]

    if effective_state == "UNKNOWN":
        reasons.append("unknown opportunity state fails closed to cash")
        action = "CASH_ONLY"
        active: list[dict[str, Any]] = []
    elif effective_state == "NO_TRADE":
        reasons.append("source-grounded no-trade state routes to cash")
        action = "CASH_ONLY"
        active = []
    else:
        active = [
            s
            for s in normalized
            if s["authorization"] in {"RESEARCH_ONLY", "PAPER_ONLY"}
            and s["authorization_validation"]["valid"]
        ]
        if invalid_authorized:
            reasons.append("one or more claimed sleeve authorizations failed artifact-bound validation")
        if not active:
            action = "CASH_ONLY"
            reasons.append("no independently artifact-authorized sleeve is available")
        else:
            action = "ROUTE_TO_INDEPENDENTLY_AUTHORIZED_SLEEVES"
            reasons.append("opportunity state is validated and only artifact-authorized sleeves are eligible")

    paper_sleeves = [s["name"] for s in active if s["authorization"] == "PAPER_ONLY"]
    research_sleeves = [s["name"] for s in active if s["authorization"] == "RESEARCH_ONLY"]
    return {
        "contract_version": CONTRACT["version"],
        "requested_opportunity_state": requested_state,
        "effective_opportunity_state": effective_state,
        "action": action,
        "active_sleeves": [s["name"] for s in active],
        "research_only_sleeves": research_sleeves,
        "paper_only_sleeves": paper_sleeves,
        "invalid_claimed_authorizations": invalid_authorized,
        "reasons": reasons,
        "classifier": dict(classifier) if classifier else None,
        "classifier_handoff_validation": classifier_check,
        "live_trading_authorized": False,
        "portfolio_optimization_authorized": False,
    }


def current_stub() -> dict[str, Any]:
    """Emit the only R01-supported current state: UNKNOWN -> CASH_ONLY."""
    if not SOURCE_NOTES.exists():
        raise FileNotFoundError(SOURCE_NOTES)
    decision = route("UNKNOWN")
    payload = {
        "contract": CONTRACT,
        "source_notes_sha256": sha256_file(SOURCE_NOTES),
        "decision": decision,
        "interpretation_boundary": (
            "R01 freezes fail-closed router behavior only. It does not implement or validate "
            "a market opportunity classifier and does not authorize a strategy."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    STUB.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(current_stub(), ensure_ascii=False, indent=2))
