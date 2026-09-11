#!/usr/bin/env python3
"""Build deterministic point-in-time semantic event episodes for V4.18-C.

This stage is deliberately market-blind. It reads only the causal-event allow-list,
the persisted frozen market calendar, and a text-only cluster freeze artifact.
It never reads price, return, P&L, X02, industry, or present-day concept data.

The online clustering contract is prospective and append-only:
- process one frozen trading session at a time;
- form same-day connected components at the frozen pairwise similarity threshold;
- compare each component only with clusters that existed before the session;
- attach to the single active historical cluster with the highest pairwise match;
- ties break by lexical cluster_id;
- a component never merges two pre-existing historical clusters;
- after > quiet_reset_sessions with no assignment, a matching event starts a new episode.

Because same-day components are resolved from a day-start snapshot, arbitrary source row
order cannot change history. Future events never rewrite prior assignments or membership.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from v4_18_event_text_features import (
    SIMILARITY_METRIC,
    TEXT_FEATURE_VERSION,
    binary_cosine,
    normalize_title,
    text_tokens,
)

BUILDER_VERSION = "v4.18-c.cluster-replay.1"
ASSIGNMENT_ALGORITHM = "prospective_single_linkage_same_day_batch_v1"
ALLOWED_EVENT_FIELDS = [
    "event_id",
    "instrument",
    "stock_name",
    "title",
    "announcement_type",
    "published_date",
    "available_trade_date",
    "causal_status",
    "calendar_sha256",
]


@dataclass
class ClusterState:
    cluster_id: str
    first_trade_date: str
    first_session_index: int
    last_trade_date: str
    last_session_index: int
    event_ids: list[str] = field(default_factory=list)
    event_tokens: list[frozenset[str]] = field(default_factory=list)
    instruments_first_seen: dict[str, tuple[str, int]] = field(default_factory=dict)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--events", default="data_lake/derived/v4_18_causal_events/events.parquet")
    p.add_argument("--calendar", default="data_lake/derived/v4_18_causal_events/market_sessions.parquet")
    p.add_argument("--freeze", default="output/v4_18_event_cluster_freeze_v1.json")
    p.add_argument("--research-start", required=True, help="YYYY-MM-DD research boundary for burn-in")
    p.add_argument("--through", default=None, help="optional last available_trade_date to replay, YYYY-MM-DD")
    p.add_argument("--assignments", default="data_lake/derived/v4_18_clusters/event_assignments.parquet")
    p.add_argument("--membership", default="data_lake/derived/v4_18_clusters/cluster_membership.parquet")
    p.add_argument("--manifest", default="output/v4_18_cluster_replay_manifest.json")
    return p.parse_args()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_calendar(path: Path) -> tuple[pd.DataFrame, str, dict[str, int]]:
    required = {
        "trade_date", "active_instruments", "calendar_sha256",
        "calendar_artifact_sha256", "calendar_version",
    }
    cal = pd.read_parquet(path)
    missing = required - set(cal.columns)
    if missing:
        raise SystemExit(f"calendar artifact missing fields: {sorted(missing)}")
    if cal.empty:
        raise SystemExit("calendar artifact is empty")

    dates = pd.to_datetime(cal["trade_date"], errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise SystemExit("calendar trade_date must be parseable, unique, and increasing")
    trade_dates = dates.dt.date.astype(str).tolist()

    hashes = set(cal["calendar_sha256"].astype(str))
    artifact_hashes = set(cal["calendar_artifact_sha256"].astype(str))
    if len(hashes) != 1 or len(artifact_hashes) != 1:
        raise SystemExit("calendar artifact must contain exactly one date hash and one artifact hash")
    calendar_hash = next(iter(hashes))
    artifact_hash = next(iter(artifact_hashes))

    expected_date_hash = hashlib.sha256("\n".join(trade_dates).encode("utf-8")).hexdigest()
    if calendar_hash != expected_date_hash:
        raise SystemExit("calendar_sha256 does not match persisted ordered trade_date list")
    artifact_lines = "\n".join(
        f"{day}|{int(count)}"
        for day, count in zip(trade_dates, cal["active_instruments"])
    )
    expected_artifact_hash = hashlib.sha256(artifact_lines.encode("utf-8")).hexdigest()
    if artifact_hash != expected_artifact_hash:
        raise SystemExit("calendar_artifact_sha256 does not match persisted session artifact")

    return cal, calendar_hash, {day: i for i, day in enumerate(trade_dates)}


def load_freeze(path: Path, calendar_hash: str) -> dict:
    freeze = json.loads(path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if not bool(freeze.get("validation", {}).get("pass", False)):
        failures.append("freeze validation.pass is not true")
    if not bool(freeze.get("market_blind", False)):
        failures.append("freeze is not market_blind=true")
    if bool(freeze.get("x02_returns_read", True)):
        failures.append("freeze indicates X02 returns may have been read")
    if freeze.get("text_feature_version") != TEXT_FEATURE_VERSION:
        failures.append("text_feature_version mismatch")
    if freeze.get("similarity_metric") != SIMILARITY_METRIC:
        failures.append("similarity_metric mismatch")
    if freeze.get("calendar_sha256") != calendar_hash:
        failures.append("freeze/calendar hash mismatch")

    threshold = freeze.get("similarity_threshold")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        failures.append("invalid similarity_threshold")
        threshold = -1.0
    if not 0.0 <= threshold <= 1.0:
        failures.append("similarity_threshold outside [0,1]")

    lifecycle = freeze.get("lifecycle", {})
    if not bool(lifecycle.get("same_day_batching_required", False)):
        failures.append("same-day batching is not frozen as required")
    if bool(lifecycle.get("retroactive_existing_cluster_merge_allowed", True)):
        failures.append("freeze allows retroactive historical cluster merges")
    if int(lifecycle.get("research_start_burn_in_sessions", -1)) < 0:
        failures.append("invalid research_start_burn_in_sessions")
    if int(lifecycle.get("quiet_reset_sessions", -1)) < 0:
        failures.append("invalid quiet_reset_sessions")

    assignment = freeze.get("assignment_algorithm", {})
    if assignment.get("name") != ASSIGNMENT_ALGORITHM:
        failures.append(
            f"freeze assignment algorithm must be {ASSIGNMENT_ALGORITHM!r}; "
            "regenerate the text-only freeze with the V4.18-C contract"
        )
    if failures:
        raise SystemExit("V4.18-C refused cluster freeze: " + "; ".join(failures))
    return freeze


def load_events(path: Path, calendar_hash: str, session_index: dict[str, int], through: str | None) -> pd.DataFrame:
    # Explicit columns= is the market-blind I/O boundary.
    try:
        events = pd.read_parquet(path, columns=ALLOWED_EVENT_FIELDS)
    except Exception as exc:
        raise SystemExit(f"cannot read causal event allow-list from {path}: {exc}") from exc
    events = events[events["causal_status"].astype(str).eq("AVAILABLE_NEXT_SESSION")].copy()
    if events.empty:
        raise SystemExit("no AVAILABLE_NEXT_SESSION events for cluster replay")
    if events["event_id"].astype(str).duplicated().any():
        raise SystemExit("duplicate event_id in causal event view")
    event_hashes = set(events["calendar_sha256"].dropna().astype(str))
    if event_hashes != {calendar_hash}:
        raise SystemExit(f"event/calendar hash mismatch: {sorted(event_hashes)} vs {calendar_hash}")

    avail = pd.to_datetime(events["available_trade_date"], errors="coerce")
    if avail.isna().any():
        raise SystemExit("AVAILABLE_NEXT_SESSION rows contain invalid available_trade_date")
    events["available_trade_date"] = avail.dt.date.astype(str)
    if through is not None:
        events = events[events["available_trade_date"] <= through].copy()
    unknown = sorted(set(events["available_trade_date"]) - set(session_index))
    if unknown:
        raise SystemExit(f"events reference dates absent from frozen calendar: {unknown[:10]}")
    if events.empty:
        raise SystemExit("no events remain after --through cutoff")

    events["session_index"] = events["available_trade_date"].map(session_index).astype(int)
    events["normalized_title"] = [
        normalize_title(title, name)
        for title, name in zip(events["title"], events["stock_name"])
    ]
    events["tokens"] = events["normalized_title"].map(text_tokens)
    # Empty-token rows cannot make a defensible semantic match. They receive singleton episodes.
    return events.sort_values(["session_index", "event_id"]).reset_index(drop=True)


def connected_components(rows: list[dict], threshold: float) -> list[list[int]]:
    """Same-day single-linkage components, computed before historical attachment."""
    n = len(rows)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    for i in range(n):
        if not rows[i]["tokens"]:
            continue
        for j in range(i + 1, n):
            if not rows[j]["tokens"]:
                continue
            if binary_cosine(rows[i]["tokens"], rows[j]["tokens"]) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda ids: tuple(str(rows[i]["event_id"]) for i in ids))


def component_cluster_score(component: list[dict], cluster: ClusterState) -> float:
    best = 0.0
    for event in component:
        tokens = event["tokens"]
        if not tokens:
            continue
        for prior_tokens in cluster.event_tokens:
            score = binary_cosine(tokens, prior_tokens)
            if score > best:
                best = score
    return best


def new_cluster_id(trade_date: str, component: Iterable[dict]) -> str:
    event_ids = sorted(str(row["event_id"]) for row in component)
    seed = f"{BUILDER_VERSION}|{trade_date}|" + "|".join(event_ids)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def novelty_bin(age: int) -> str:
    if age == 0:
        return "FIRST_SEEN"
    if age <= 5:
        return "EARLY"
    if age <= 20:
        return "RECENT"
    return "OLD"


def replay(
    events: pd.DataFrame,
    threshold: float,
    quiet_reset_sessions: int,
    burn_in_sessions: int,
    research_start_index: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    clusters: dict[str, ClusterState] = {}
    assignments: list[dict] = []
    ambiguous_historical_matches = 0

    for trade_date, day_frame in events.groupby("available_trade_date", sort=True):
        day_rows = day_frame.sort_values("event_id").to_dict("records")
        day_index = int(day_rows[0]["session_index"])
        comps = [[day_rows[i] for i in ids] for ids in connected_components(day_rows, threshold)]

        # Freeze the candidate set at start-of-day. Same-day components cannot change
        # one another's historical attachment decisions.
        active = {
            cid: state
            for cid, state in clusters.items()
            if day_index - state.last_session_index <= quiet_reset_sessions
        }
        decisions: list[tuple[list[dict], str | None, float]] = []
        for component in comps:
            matches: list[tuple[float, str]] = []
            for cid, state in active.items():
                score = component_cluster_score(component, state)
                if score >= threshold:
                    matches.append((score, cid))
            if matches:
                matches.sort(key=lambda item: (-item[0], item[1]))
                if len(matches) > 1:
                    ambiguous_historical_matches += 1
                decisions.append((component, matches[0][1], matches[0][0]))
            else:
                decisions.append((component, None, 0.0))

        touched: dict[str, list[dict]] = {}
        match_scores: dict[str, dict[str, float]] = {}
        for component, cid, score in decisions:
            if cid is None:
                cid = new_cluster_id(str(trade_date), component)
                if cid in clusters:
                    raise SystemExit(f"cluster_id collision: {cid}")
                clusters[cid] = ClusterState(
                    cluster_id=cid,
                    first_trade_date=str(trade_date),
                    first_session_index=day_index,
                    last_trade_date=str(trade_date),
                    last_session_index=day_index,
                )
            touched.setdefault(cid, []).extend(component)
            for row in component:
                match_scores.setdefault(cid, {})[str(row["event_id"])] = float(score)

        # Apply the whole day's decisions only after every component was assigned.
        for cid in sorted(touched):
            state = clusters[cid]
            rows = sorted(touched[cid], key=lambda row: str(row["event_id"]))
            prior_instruments = set(state.instruments_first_seen)
            today_new_instruments = sorted(
                {str(row["instrument"]) for row in rows} - prior_instruments
            )
            for row in rows:
                event_id = str(row["event_id"])
                instrument = str(row["instrument"])
                state.event_ids.append(event_id)
                state.event_tokens.append(row["tokens"])
                state.instruments_first_seen.setdefault(instrument, (str(trade_date), day_index))
            state.last_trade_date = str(trade_date)
            state.last_session_index = day_index

            age = day_index - state.first_session_index
            known_docs = len(state.event_ids)
            known_stocks = len(state.instruments_first_seen)
            burn_in_complete = day_index - research_start_index >= burn_in_sessions
            for row in rows:
                assignments.append(
                    {
                        "event_id": str(row["event_id"]),
                        "instrument": str(row["instrument"]),
                        "available_trade_date": str(trade_date),
                        "session_index": day_index,
                        "cluster_id": cid,
                        "cluster_first_available_trade_date": state.first_trade_date,
                        "cluster_first_session_index": state.first_session_index,
                        "age_trading_days": age,
                        "h04_age_bin_at_event": novelty_bin(age),
                        "known_document_count_after_batch": known_docs,
                        "known_stock_count_after_batch": known_stocks,
                        "new_stock_count_today": len(today_new_instruments),
                        "group_formed_after_batch": known_stocks >= 2,
                        "historical_attachment_similarity": match_scores[cid][str(row["event_id"])],
                        "burn_in_complete": bool(burn_in_complete),
                        "builder_version": BUILDER_VERSION,
                    }
                )

    membership_rows: list[dict] = []
    for cid, state in sorted(clusters.items()):
        for instrument, (first_date, first_index) in sorted(state.instruments_first_seen.items()):
            membership_rows.append(
                {
                    "cluster_id": cid,
                    "instrument": instrument,
                    "member_first_available_trade_date": first_date,
                    "member_first_session_index": first_index,
                    "cluster_first_available_trade_date": state.first_trade_date,
                    "cluster_first_session_index": state.first_session_index,
                    "builder_version": BUILDER_VERSION,
                }
            )

    assignment_frame = pd.DataFrame(assignments).sort_values(
        ["available_trade_date", "cluster_id", "event_id"]
    ).reset_index(drop=True)
    membership_frame = pd.DataFrame(membership_rows).sort_values(
        ["cluster_id", "member_first_session_index", "instrument"]
    ).reset_index(drop=True)
    metrics = {
        "event_rows": int(len(assignment_frame)),
        "cluster_episodes": int(assignment_frame["cluster_id"].nunique()),
        "membership_rows": int(len(membership_frame)),
        "group_formed_event_rows": int(assignment_frame["group_formed_after_batch"].sum()),
        "ambiguous_historical_component_matches_resolved_without_merge": ambiguous_historical_matches,
    }
    return assignment_frame, membership_frame, metrics


def main() -> None:
    args = parse_args()
    calendar_path = Path(args.calendar)
    events_path = Path(args.events)
    freeze_path = Path(args.freeze)
    calendar, calendar_hash, session_index = load_calendar(calendar_path)
    freeze = load_freeze(freeze_path, calendar_hash)

    research_start = pd.Timestamp(args.research_start).date().isoformat()
    research_candidates = [idx for day, idx in session_index.items() if day >= research_start]
    if not research_candidates:
        raise SystemExit("--research-start is after the frozen calendar")
    research_start_index = min(research_candidates)

    through = pd.Timestamp(args.through).date().isoformat() if args.through else None
    events = load_events(events_path, calendar_hash, session_index, through)
    lifecycle = freeze["lifecycle"]
    assignments, membership, metrics = replay(
        events=events,
        threshold=float(freeze["similarity_threshold"]),
        quiet_reset_sessions=int(lifecycle["quiet_reset_sessions"]),
        burn_in_sessions=int(lifecycle["research_start_burn_in_sessions"]),
        research_start_index=research_start_index,
    )

    assignments_path = Path(args.assignments)
    membership_path = Path(args.membership)
    manifest_path = Path(args.manifest)
    for path in (assignments_path, membership_path, manifest_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    assignments.to_parquet(assignments_path, index=False)
    membership.to_parquet(membership_path, index=False)

    manifest = {
        "builder_version": BUILDER_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scientific_status": "MARKET_BLIND_POINT_IN_TIME_CLUSTER_REPLAY_NOT_PERFORMANCE_TESTED",
        "market_blind": True,
        "x02_returns_read": False,
        "allowed_event_fields": ALLOWED_EVENT_FIELDS,
        "research_start": research_start,
        "through": through,
        "calendar": {
            "path": str(calendar_path),
            "sha256": sha256_file(calendar_path),
            "calendar_sha256": calendar_hash,
            "session_count": int(len(calendar)),
        },
        "freeze": {
            "path": str(freeze_path),
            "sha256": sha256_file(freeze_path),
            "cluster_config_version": freeze.get("cluster_config_version"),
            "similarity_threshold": float(freeze["similarity_threshold"]),
        },
        "assignment_contract": {
            "name": ASSIGNMENT_ALGORITHM,
            "same_day_graph": "connected components using frozen pairwise similarity threshold",
            "historical_attachment": "maximum pairwise similarity to active pre-day cluster",
            "historical_tie_breaker": "lexical cluster_id",
            "same_day_decisions_use_day_start_history_only": True,
            "retroactive_existing_cluster_merge_allowed": False,
            "quiet_reset_sessions": int(lifecycle["quiet_reset_sessions"]),
            "cluster_id": "sha256(builder_version|first_trade_date|sorted founding event_ids)",
        },
        "metrics": metrics,
        "outputs": {
            "assignments": str(assignments_path),
            "assignments_sha256": sha256_file(assignments_path),
            "membership": str(membership_path),
            "membership_sha256": sha256_file(membership_path),
        },
        "validation": {
            "pass": True,
            "future_events_can_rewrite_past": False,
            "same_day_source_order_used": False,
            "market_or_return_fields_read": False,
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
