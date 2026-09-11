#!/usr/bin/env python3
"""Machine gate that must PASS before the first formal H04/H05 outcome test.

This gate intentionally does not calculate returns.  It verifies that every
preregistered upstream causal artifact belongs to one coherent production
research chain and refuses smoke/stale evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GATE_VERSION = "v4.18-h04-h05-unlock.1"
EXPECTED_PREREG_VERSION = "v4.18-h04-h05-prereg.1"
EXPECTED_V418_VIEW = "v4.18-a.2"
EXPECTED_ASSIGNMENT_ALGORITHM = "prospective_single_linkage_same_day_batch_v1"
EXPECTED_TEXT_FEATURE_VERSION = "v4.18-b.text.1"
EXPECTED_SIMILARITY_METRIC = "binary_cosine_char_2_3gram_ascii_token"
EXPECTED_BURN_IN = 60
EXPECTED_QUIET_RESET = 20
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--prereg", default="v4_18_h04_h05_prereg_v1.json")
    p.add_argument("--v417-gate", default="output/v4_17_full_backfill_gate.json")
    p.add_argument("--source-audit", default="output/v4_17_event_source_audit.json")
    p.add_argument("--causal-manifest", default="output/v4_18_causal_event_view_manifest.json")
    p.add_argument("--cluster-freeze", default="output/v4_18_event_cluster_freeze_v1.json")
    p.add_argument("--replay-manifest", default="output/v4_18_cluster_replay_manifest.json")
    p.add_argument("--output", default="output/v4_18_h04_h05_unlock_gate.json")
    return p.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"missing required evidence: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"cannot parse JSON evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"JSON evidence must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_sha256(value: object) -> bool:
    return bool(SHA256_RE.fullmatch(str(value or "")))


def add(failures: list[str], condition: bool, message: str) -> None:
    if condition:
        failures.append(message)


def artifact_path(raw: object, manifest_path: Path) -> Path:
    p = Path(str(raw or ""))
    if p.is_absolute():
        return p
    # Production manifests are repository-relative.  For synthetic CI manifests
    # stored outside the repository, a sibling relative path is also accepted.
    if p.exists():
        return p
    candidate = manifest_path.parent / p
    return candidate


def verify_hashed_artifact(
    failures: list[str], manifest_path: Path, raw_path: object, expected_hash: object, label: str
) -> None:
    p = artifact_path(raw_path, manifest_path)
    add(failures, not str(raw_path or ""), f"{label}: missing artifact path")
    add(failures, not is_sha256(expected_hash), f"{label}: missing/invalid SHA-256 in manifest")
    if not p.exists():
        failures.append(f"{label}: artifact not found: {p}")
        return
    if is_sha256(expected_hash):
        actual = sha256_file(p)
        add(failures, actual != str(expected_hash), f"{label}: SHA-256 mismatch")


def main() -> None:
    args = parse_args()
    paths = {
        "prereg": Path(args.prereg),
        "v417": Path(args.v417_gate),
        "source_audit": Path(args.source_audit),
        "causal": Path(args.causal_manifest),
        "freeze": Path(args.cluster_freeze),
        "replay": Path(args.replay_manifest),
    }
    prereg = load_json(paths["prereg"])
    v417 = load_json(paths["v417"])
    source_audit = load_json(paths["source_audit"])
    causal = load_json(paths["causal"])
    freeze = load_json(paths["freeze"])
    replay = load_json(paths["replay"])

    failures: list[str] = []

    # Preregistration is the root of the evidence chain.
    add(failures, prereg.get("prereg_version") != EXPECTED_PREREG_VERSION, "unexpected prereg version")
    add(
        failures,
        prereg.get("scientific_status") != "PREREGISTERED_NOT_TESTED",
        "prereg scientific status is not PREREGISTERED_NOT_TESTED",
    )
    add(
        failures,
        bool(prereg.get("parameter_search_in_primary_test_allowed", True)),
        "primary-test parameter search is not forbidden",
    )
    window = prereg.get("research_window", {})
    start = str(window.get("event_start", ""))
    end = str(window.get("event_end", ""))
    add(failures, not start or not end, "preregistered event window is missing")
    expected_years = list(range(int(start[:4]), int(end[:4]) + 1)) if start and end else []

    # V4.17-C exact-window source archive gate.
    add(failures, not str(v417.get("gate_version", "")).startswith("v4.17-c."), "unsupported V4.17-C gate")
    add(failures, v417.get("requested_start") != start, "V4.17-C start != prereg start")
    add(failures, v417.get("requested_end") != end, "V4.17-C end != prereg end")
    add(failures, not bool(v417.get("validation", {}).get("pass", False)), "V4.17-C validation did not PASS")
    add(
        failures,
        not bool(v417.get("research_eligibility", {}).get("h04_h05_allowed", False)),
        "V4.17-C does not allow H04/H05",
    )
    completion = v417.get("completion", {})
    add(failures, completion.get("failed_years") not in ([], None), "V4.17-C has failed years")
    add(
        failures,
        sorted(completion.get("passed_years", [])) != expected_years,
        "V4.17-C passed years do not cover the preregistered window",
    )
    add(
        failures,
        completion.get("terminal_request_days") != completion.get("expected_calendar_days"),
        "V4.17-C does not have one terminal request result for every calendar day",
    )

    # V4.17-D: second-source audit must have inspected the canonical annual archive,
    # not legacy fixtures occupying different paths.
    add(failures, source_audit.get("audit_only") is not True, "V4.17-D output is not audit_only=true")
    add(
        failures,
        source_audit.get("canonicalizer_used_for_trading_features") is not False,
        "V4.17-D canonicalizer may have leaked into trading features",
    )
    add(
        failures,
        source_audit.get("source_loader_validation_pass") is not True,
        "V4.17-D canonical source loader did not PASS",
    )
    em = source_audit.get("loader_diagnostics", {}).get("eastmoney", {})
    add(failures, bool(em.get("canonical_contract_violations", ["missing"])), "V4.17-D canonical Eastmoney contract violations exist")
    add(
        failures,
        sorted(em.get("canonical_years", [])) != expected_years,
        "V4.17-D did not audit canonical annual files for every research year",
    )
    add(
        failures,
        int(em.get("canonical_files", 0) or 0) < len(expected_years),
        "V4.17-D audited fewer canonical annual files than expected years",
    )
    add(failures, int(em.get("canonical_rows", 0) or 0) <= 0, "V4.17-D canonical Eastmoney audit is empty")
    add(failures, int(source_audit.get("cninfo_unique_notice_rows", 0) or 0) <= 0, "V4.17-D CNINFO evidence is empty")
    add(failures, int(source_audit.get("exact_canonical_matches", 0) or 0) <= 0, "V4.17-D found no cross-source exact canonical match")

    # V4.18-A exact-window causal availability view.
    add(failures, causal.get("view_version") != EXPECTED_V418_VIEW, "unexpected V4.18-A view version")
    add(failures, causal.get("requested_start") != start, "V4.18-A start != prereg start")
    add(failures, causal.get("requested_end") != end, "V4.18-A end != prereg end")
    add(failures, not bool(causal.get("validation", {}).get("pass", False)), "V4.18-A validation did not PASS")
    upstream = causal.get("upstream_v417_gate", {})
    add(failures, upstream.get("requested_start") != start or upstream.get("requested_end") != end, "V4.18-A was built from a different V4.17-C window")
    add(failures, upstream.get("pass") is not True or upstream.get("h04_h05_allowed") is not True, "V4.18-A upstream V4.17-C evidence was not green")
    availability = causal.get("availability_contract", {})
    add(failures, availability.get("same_day_use_allowed") is not False, "V4.18-A allows same-day event use")
    add(failures, availability.get("intraday_timestamp_fabricated") is not False, "V4.18-A fabricated intraday timestamps")
    add(failures, availability.get("live_calendar_api_used") is not False, "V4.18-A used a live calendar API")
    causal_calendar = causal.get("calendar", {})
    calendar_hash = str(causal_calendar.get("calendar_sha256", ""))
    artifact_hash = str(causal_calendar.get("calendar_artifact_sha256", ""))
    add(failures, not is_sha256(calendar_hash), "V4.18-A calendar_sha256 is invalid")
    add(failures, not is_sha256(artifact_hash), "V4.18-A calendar_artifact_sha256 is invalid")
    add(failures, int(causal_calendar.get("session_count", 0) or 0) <= 0, "V4.18-A frozen calendar is empty")

    # V4.18-B text-only calibration/freeze.
    add(failures, freeze.get("market_blind") is not True, "V4.18-B is not market_blind=true")
    add(failures, freeze.get("x02_returns_read") is not False, "V4.18-B may have read X02 returns")
    add(failures, not bool(freeze.get("validation", {}).get("pass", False)), "V4.18-B validation did not PASS")
    add(failures, freeze.get("text_feature_version") != EXPECTED_TEXT_FEATURE_VERSION, "unexpected V4.18-B text feature version")
    add(failures, freeze.get("similarity_metric") != EXPECTED_SIMILARITY_METRIC, "unexpected V4.18-B similarity metric")
    add(failures, freeze.get("calendar_sha256") != calendar_hash, "V4.18-B frozen calendar != V4.18-A calendar")
    lifecycle = freeze.get("lifecycle", {})
    add(failures, int(lifecycle.get("research_start_burn_in_sessions", -1)) != EXPECTED_BURN_IN, "V4.18-B burn-in != preregistered 60 sessions")
    add(failures, int(lifecycle.get("quiet_reset_sessions", -1)) != EXPECTED_QUIET_RESET, "V4.18-B quiet reset != preregistered 20 sessions")
    add(failures, lifecycle.get("same_day_batching_required") is not True, "V4.18-B same-day batching not required")
    add(failures, lifecycle.get("retroactive_existing_cluster_merge_allowed") is not False, "V4.18-B permits retroactive cluster merge")
    assignment = freeze.get("assignment_algorithm", {})
    add(failures, assignment.get("name") != EXPECTED_ASSIGNMENT_ALGORITHM, "V4.18-B assignment algorithm is not the frozen V4.18-C contract")
    add(
        failures,
        freeze.get("validation", {}).get("assignment_algorithm_frozen_before_return_join") is not True,
        "V4.18-B assignment algorithm was not proven frozen before return join",
    )

    # V4.18-C append-only prospective replay.
    add(failures, replay.get("market_blind") is not True, "V4.18-C is not market_blind=true")
    add(failures, replay.get("x02_returns_read") is not False, "V4.18-C may have read X02 returns")
    add(failures, not bool(replay.get("validation", {}).get("pass", False)), "V4.18-C validation did not PASS")
    add(failures, replay.get("research_start") != start, "V4.18-C research_start != prereg start")
    replay_calendar = replay.get("calendar", {})
    add(failures, replay_calendar.get("calendar_sha256") != calendar_hash, "V4.18-C calendar != V4.18-A calendar")
    replay_freeze = replay.get("freeze", {})
    add(failures, replay_freeze.get("cluster_config_version") != freeze.get("cluster_config_version"), "V4.18-C used a different cluster freeze version")
    add(failures, float(replay_freeze.get("similarity_threshold", -1)) != float(freeze.get("similarity_threshold", -2)), "V4.18-C used a different similarity threshold")
    replay_assignment = replay.get("assignment_contract", {})
    add(failures, replay_assignment.get("name") != EXPECTED_ASSIGNMENT_ALGORITHM, "V4.18-C assignment algorithm mismatch")
    add(failures, replay_assignment.get("retroactive_existing_cluster_merge_allowed") is not False, "V4.18-C permits retroactive historical merge")
    add(failures, replay.get("validation", {}).get("future_events_can_rewrite_past") is not False, "V4.18-C does not prove future-history invariance")
    add(failures, replay.get("validation", {}).get("same_day_source_order_used") is not False, "V4.18-C is source-row-order dependent")
    add(failures, replay.get("validation", {}).get("market_or_return_fields_read") is not False, "V4.18-C may have consumed market/return fields")
    metrics = replay.get("metrics", {})
    add(failures, int(metrics.get("event_rows", 0) or 0) <= 0, "V4.18-C replay is empty")
    add(failures, int(metrics.get("cluster_episodes", 0) or 0) <= 0, "V4.18-C produced no cluster episodes")

    verify_hashed_artifact(
        failures,
        paths["replay"],
        replay_calendar.get("path"),
        replay_calendar.get("sha256"),
        "V4.18-C frozen calendar file",
    )
    outputs = replay.get("outputs", {})
    verify_hashed_artifact(
        failures, paths["replay"], outputs.get("assignments"), outputs.get("assignments_sha256"), "V4.18-C assignments"
    )
    verify_hashed_artifact(
        failures, paths["replay"], outputs.get("membership"), outputs.get("membership_sha256"), "V4.18-C membership"
    )

    report = {
        "gate_version": GATE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scientific_status": "READY_FOR_FIRST_FORMAL_H04_H05_TEST" if not failures else "BLOCKED",
        "research_window": {"event_start": start, "event_end": end},
        "calendar_sha256": calendar_hash or None,
        "evidence": {name: str(path) for name, path in paths.items()},
        "experiment_unlock": {
            "h04_h05_allowed": not failures,
            "parameter_search_in_primary_test_allowed": False,
            "next_action_if_pass": "run the preregistered first formal H04/H05 test exactly once before any tuning",
            "next_action_if_fail": "repair upstream evidence; do not run or inspect formal H04/H05 outcomes",
        },
        "validation": {"pass": not failures, "failures": failures},
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit("H04/H05 remain blocked: " + "; ".join(failures))


if __name__ == "__main__":
    main()
