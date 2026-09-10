#!/usr/bin/env python3
"""Prepare a deterministic, market-blind text audit for V4.18 event clustering.

The script reads only an explicit allow-list of causal-event columns plus the
persisted V4.18 market-session artifact.  It never reads price/return/P&L data.
"""

from __future__ import annotations

import argparse
import heapq
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from v4_18_event_text_features import (
    SIMILARITY_METRIC,
    TEXT_FEATURE_VERSION,
    binary_cosine,
    normalize_title,
    stable_sha256,
    text_tokens,
)

AUDIT_VERSION = "v4.18-b.audit.1"
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
SIMILARITY_BANDS = [
    (0.10, 0.20),
    (0.20, 0.30),
    (0.30, 0.40),
    (0.40, 0.50),
    (0.50, 0.60),
    (0.60, 0.70),
    (0.70, 0.85),
    (0.85, 1.0000001),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--events",
        default="data_lake/derived/v4_18_causal_events/events.parquet",
    )
    p.add_argument(
        "--calendar",
        default="data_lake/derived/v4_18_causal_events/market_sessions.parquet",
    )
    p.add_argument("--sample-per-year", type=int, default=1000)
    p.add_argument("--title-sample-per-year", type=int, default=40)
    p.add_argument("--pairs-per-band", type=int, default=40)
    p.add_argument("--candidate-cap-per-event", type=int, default=200)
    p.add_argument("--max-session-gap", type=int, default=20)
    p.add_argument(
        "--output-pairs",
        default="output/v4_18_event_text_pair_audit.csv",
    )
    p.add_argument(
        "--output-titles",
        default="output/v4_18_event_title_eligibility_audit.csv",
    )
    p.add_argument(
        "--manifest",
        default="output/v4_18_event_text_audit_manifest.json",
    )
    return p.parse_args()


def sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_rank(text: str) -> int:
    return int(stable_sha256(text)[:16], 16)


def load_calendar(path: Path) -> tuple[pd.DataFrame, str, dict[str, int]]:
    required = {
        "trade_date",
        "active_instruments",
        "calendar_sha256",
        "calendar_artifact_sha256",
        "calendar_version",
    }
    cal = pd.read_parquet(path)
    missing = required - set(cal.columns)
    if missing:
        raise SystemExit(f"calendar artifact missing fields: {sorted(missing)}")
    if cal.empty:
        raise SystemExit("calendar artifact is empty")
    hashes = set(cal["calendar_sha256"].astype(str))
    if len(hashes) != 1:
        raise SystemExit(f"calendar artifact has multiple calendar hashes: {sorted(hashes)}")
    dates = pd.to_datetime(cal["trade_date"], errors="coerce")
    if dates.isna().any():
        raise SystemExit("calendar artifact contains unparseable trade_date")
    if not dates.is_monotonic_increasing or dates.duplicated().any():
        raise SystemExit("calendar trade_date must be unique and increasing")
    trade_dates = dates.dt.date.astype(str).tolist()
    session_index = {day: i for i, day in enumerate(trade_dates)}
    return cal, next(iter(hashes)), session_index


def load_events(path: Path, calendar_hash: str, session_index: dict[str, int]) -> pd.DataFrame:
    # The column allow-list is the market-blind boundary: even if the parquet
    # later gains return columns, this stage does not read them.
    try:
        events = pd.read_parquet(path, columns=ALLOWED_EVENT_FIELDS)
    except Exception as exc:
        raise SystemExit(f"cannot read required market-blind event fields from {path}: {exc}") from exc

    if events.empty:
        raise SystemExit("causal event view is empty")
    events = events[events["causal_status"].astype(str).eq("AVAILABLE_NEXT_SESSION")].copy()
    if events.empty:
        raise SystemExit("no AVAILABLE_NEXT_SESSION events for text audit")

    event_hashes = set(events["calendar_sha256"].dropna().astype(str))
    if event_hashes != {calendar_hash}:
        raise SystemExit(
            "event/calendar hash mismatch: "
            f"event_hashes={sorted(event_hashes)} calendar_hash={calendar_hash}"
        )

    avail = pd.to_datetime(events["available_trade_date"], errors="coerce")
    if avail.isna().any():
        raise SystemExit("AVAILABLE_NEXT_SESSION rows contain null/unparseable available_trade_date")
    events["available_trade_date"] = avail.dt.date.astype(str)
    unknown = sorted(set(events["available_trade_date"]) - set(session_index))
    if unknown:
        raise SystemExit(f"events reference dates absent from frozen calendar: {unknown[:10]}")

    if events["event_id"].astype(str).duplicated().any():
        raise SystemExit("duplicate event_id in causal event view")

    events["session_index"] = events["available_trade_date"].map(session_index).astype(int)
    events["audit_year"] = events["available_trade_date"].str[:4].astype(int)
    events["_rank"] = events["event_id"].astype(str).map(hash_rank)
    events["normalized_title"] = [
        normalize_title(title, name)
        for title, name in zip(events["title"], events["stock_name"])
    ]
    events["tokens"] = events["normalized_title"].map(text_tokens)
    events = events[events["tokens"].map(bool)].copy()
    if events.empty:
        raise SystemExit("all normalized event titles are empty")
    return events


def stratified_event_sample(events: pd.DataFrame, n_per_year: int) -> pd.DataFrame:
    if n_per_year < 1:
        raise SystemExit("--sample-per-year must be >= 1")
    parts = []
    for _, group in events.groupby("audit_year", sort=True):
        parts.append(group.nsmallest(min(n_per_year, len(group)), "_rank"))
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(["available_trade_date", "event_id"]).reset_index(drop=True)


def similarity_band(score: float) -> str | None:
    for low, high in SIMILARITY_BANDS:
        if low <= score < high:
            return f"[{low:.2f},{min(high, 1.0):.2f}{']' if high > 1.0 else ')'}"
    return None


def _push_smallest(heap: list, keep: int, key: int, pair_id: str, record: dict) -> None:
    item = (-key, pair_id, record)
    if len(heap) < keep:
        heapq.heappush(heap, item)
        return
    # heap[0] is the largest retained key because keys are negated.
    largest_retained = -heap[0][0]
    if key < largest_retained:
        heapq.heapreplace(heap, item)


def build_pair_audit(
    sample: pd.DataFrame,
    pairs_per_band: int,
    candidate_cap_per_event: int,
    max_session_gap: int,
) -> pd.DataFrame:
    if pairs_per_band < 1 or candidate_cap_per_event < 1 or max_session_gap < 0:
        raise SystemExit("pair sampling arguments must be positive and max-session-gap >= 0")

    rows = sample.to_dict("records")
    inverted: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        for token in row["tokens"]:
            inverted[token].append(idx)

    heaps: dict[str, list] = defaultdict(list)
    seen_pairs: set[tuple[int, int]] = set()

    for i, row in enumerate(rows):
        candidate_ids: set[int] = set()
        for token in row["tokens"]:
            candidate_ids.update(inverted[token])
        candidate_ids.discard(i)

        eligible = []
        for j in candidate_ids:
            if j <= i:
                continue
            other = rows[j]
            if str(row["instrument"]) == str(other["instrument"]):
                continue
            if abs(int(row["session_index"]) - int(other["session_index"])) > max_session_gap:
                continue
            pair = (i, j)
            if pair in seen_pairs:
                continue
            pair_key = hash_rank(
                "|".join(sorted([str(row["event_id"]), str(other["event_id"])]))
            )
            eligible.append((pair_key, j))

        eligible.sort(key=lambda item: item[0])
        for pair_key, j in eligible[:candidate_cap_per_event]:
            pair = (i, j)
            seen_pairs.add(pair)
            other = rows[j]
            score = binary_cosine(row["tokens"], other["tokens"])
            band = similarity_band(score)
            if band is None:
                continue
            event_a, event_b = sorted([str(row["event_id"]), str(other["event_id"])])
            pair_id = stable_sha256(f"{AUDIT_VERSION}|{event_a}|{event_b}")
            record = {
                "pair_id": pair_id,
                "similarity_band": band,
                "similarity": round(float(score), 8),
                "event_id_a": str(row["event_id"]),
                "event_id_b": str(other["event_id"]),
                "instrument_a": str(row["instrument"]),
                "instrument_b": str(other["instrument"]),
                "available_trade_date_a": str(row["available_trade_date"]),
                "available_trade_date_b": str(other["available_trade_date"]),
                "title_a": str(row["title"]),
                "title_b": str(other["title"]),
                "normalized_title_a": str(row["normalized_title"]),
                "normalized_title_b": str(other["normalized_title"]),
                "pair_label": "",
                "review_note": "",
            }
            _push_smallest(heaps[band], pairs_per_band, pair_key, pair_id, record)

    selected: list[dict] = []
    band_order = {similarity_band((lo + min(hi, 1.0)) / 2): idx for idx, (lo, hi) in enumerate(SIMILARITY_BANDS)}
    for band, heap in heaps.items():
        selected.extend(item[2] for item in heap)
    if not selected:
        raise SystemExit("text audit produced no candidate pairs")
    out = pd.DataFrame(selected)
    out["_band_order"] = out["similarity_band"].map(band_order)
    out = out.sort_values(["_band_order", "pair_id"]).drop(columns=["_band_order"])
    return out.reset_index(drop=True)


def build_title_audit(events: pd.DataFrame, per_year: int) -> pd.DataFrame:
    if per_year < 1:
        raise SystemExit("--title-sample-per-year must be >= 1")
    parts = []
    for _, group in events.groupby("audit_year", sort=True):
        part = group.nsmallest(min(per_year, len(group)), "_rank")
        parts.append(part)
    sample = pd.concat(parts, ignore_index=True)
    return pd.DataFrame(
        {
            "event_id": sample["event_id"].astype(str),
            "instrument": sample["instrument"].astype(str),
            "available_trade_date": sample["available_trade_date"].astype(str),
            "announcement_type": sample["announcement_type"].astype(str),
            "title": sample["title"].astype(str),
            "normalized_title": sample["normalized_title"].astype(str),
            "theme_eligibility_label": "",
            "review_note": "",
        }
    ).sort_values("event_id").reset_index(drop=True)


def main() -> None:
    args = parse_args()
    events_path = Path(args.events)
    calendar_path = Path(args.calendar)
    calendar, calendar_hash, session_index = load_calendar(calendar_path)
    events = load_events(events_path, calendar_hash, session_index)
    sampled = stratified_event_sample(events, args.sample_per_year)

    pairs = build_pair_audit(
        sampled,
        args.pairs_per_band,
        args.candidate_cap_per_event,
        args.max_session_gap,
    )
    titles = build_title_audit(events, args.title_sample_per_year)

    pairs_path = Path(args.output_pairs)
    titles_path = Path(args.output_titles)
    manifest_path = Path(args.manifest)
    for path in (pairs_path, titles_path, manifest_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    pairs.to_csv(pairs_path, index=False)
    titles.to_csv(titles_path, index=False)

    manifest = {
        "audit_version": AUDIT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_blind": True,
        "allowed_event_fields": ALLOWED_EVENT_FIELDS,
        "text_feature_version": TEXT_FEATURE_VERSION,
        "similarity_metric": SIMILARITY_METRIC,
        "similarity_bands": [
            {"low": low, "high": min(high, 1.0)} for low, high in SIMILARITY_BANDS
        ],
        "calendar": {
            "path": str(calendar_path),
            "calendar_sha256": calendar_hash,
            "session_count": int(len(calendar)),
        },
        "event_input": str(events_path),
        "available_event_rows": int(len(events)),
        "sampled_event_rows": int(len(sampled)),
        "sample_per_year": int(args.sample_per_year),
        "max_session_gap": int(args.max_session_gap),
        "candidate_cap_per_event": int(args.candidate_cap_per_event),
        "pair_audit": {
            "path": str(pairs_path),
            "rows": int(len(pairs)),
            "sha256": sha256_file(pairs_path),
        },
        "title_audit": {
            "path": str(titles_path),
            "rows": int(len(titles)),
            "sha256": sha256_file(titles_path),
        },
        "validation": {
            "pass": True,
            "return_or_pnl_fields_read": False,
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
