#!/usr/bin/env python3
"""Run the first preregistered H04/H05 performance test after the unlock gate.

The most important property of this module is I/O ordering: the machine-readable
V4.18 H04/H05 unlock artifact and preregistration are validated before this code
imports the X02 execution module or opens any price/return/P&L input.

The formal test is intentionally narrow:
- X02 remains the frozen V4.16 execution: T-1 signal, 0.5% limit buffer,
  clean_mom20_rank Top3, T 14:45 completed 5m close -> T+1 10:00;
- BASE and CONSERVATIVE costs are reused from v4_3_long_only_portfolio;
- event context is attached from V4.18-C point-in-time episodes only;
- H05 T-1 group returns are read from the same frozen BaoStock all-A-share daily
  lake used to derive the V4.18 market calendar;
- no threshold/age/breadth/core parameter search is performed.

If the unlock gate is not green, the process exits before cluster, X02, daily,
minute, return, or P&L data are read.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

RUNNER_VERSION = "v4.18-h04-h05-runner.1"
EXPECTED_UNLOCK_VERSION = "v4.18-h04-h05-unlock.1"
EXPECTED_PREREG_VERSION = "v4.18-h04-h05-prereg.1"
EXPECTED_CLUSTER_BUILDER = "v4.18-c.cluster-replay.1"
LIMIT_BUFFER = 0.005
TOP_N = 3
EXIT_LABEL = "10:00"
COST_NAMES = ("BASE", "CONSERVATIVE")
BURN_IN_SESSIONS = 60


@dataclass(frozen=True)
class Paths:
    prereg: Path
    unlock: Path
    replay_manifest: Path
    assignments: Path
    membership: Path
    calendar: Path
    daily_root: Path
    output: Path
    ledger: Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--prereg", default="v4_18_h04_h05_prereg_v1.json")
    p.add_argument("--unlock", default="output/v4_18_h04_h05_unlock_gate.json")
    p.add_argument("--replay-manifest", default="output/v4_18_cluster_replay_manifest.json")
    p.add_argument("--assignments", default="data_lake/derived/v4_18_clusters/event_assignments.parquet")
    p.add_argument("--membership", default="data_lake/derived/v4_18_clusters/cluster_membership.parquet")
    p.add_argument("--calendar", default="data_lake/derived/v4_18_causal_events/market_sessions.parquet")
    p.add_argument("--daily-root", default="data_lake/raw/baostock/equity_daily")
    p.add_argument("--output", default="output/v4_18_h04_h05_preregistered_result.json")
    p.add_argument("--ledger", default="output/v4_18_h04_h05_candidate_context.csv")
    return p.parse_args()


def _json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"missing required control artifact: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"cannot parse control artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"control artifact must be a JSON object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_control_plane(unlock_path: Path, prereg_path: Path) -> tuple[dict, dict]:
    """Validate the unlock and preregistration before any research-data I/O."""
    unlock = _json(unlock_path)
    prereg = _json(prereg_path)
    failures: list[str] = []

    if unlock.get("gate_version") != EXPECTED_UNLOCK_VERSION:
        failures.append("unexpected unlock gate version")
    if unlock.get("scientific_status") != "READY_FOR_FIRST_FORMAL_H04_H05_TEST":
        failures.append("unlock scientific_status is not READY_FOR_FIRST_FORMAL_H04_H05_TEST")
    if unlock.get("validation", {}).get("pass") is not True:
        failures.append("unlock validation.pass is not true")
    exp = unlock.get("experiment_unlock", {})
    if exp.get("h04_h05_allowed") is not True:
        failures.append("unlock does not allow H04/H05")
    if exp.get("parameter_search_in_primary_test_allowed") is not False:
        failures.append("unlock does not forbid primary-test parameter search")

    if prereg.get("prereg_version") != EXPECTED_PREREG_VERSION:
        failures.append("unexpected preregistration version")
    if prereg.get("scientific_status") != "PREREGISTERED_NOT_TESTED":
        failures.append("preregistration is not in PREREGISTERED_NOT_TESTED state")
    if prereg.get("parameter_search_in_primary_test_allowed") is not False:
        failures.append("preregistration permits parameter search")

    frozen = prereg.get("x02_frozen_contract", {})
    exact_x02 = {
        "signal_bar": "T-1 completed daily bar",
        "raw_momentum_rank20_min": 0.8,
        "clean_momentum_rank20_min": 0.8,
        "hit_count20_max": 1,
        "entry": "T 14:45 end-labelled 5m close",
        "portfolio": "Top3 equal weight",
        "primary_exit": "T+1 10:00",
        "cost_models": ["BASE", "CONSERVATIVE"],
        "ranking_may_change": False,
    }
    for key, expected in exact_x02.items():
        if frozen.get(key) != expected:
            failures.append(f"frozen X02 contract drift: {key}")

    cutoff = prereg.get("first_test_market_cutoff", {})
    if cutoff.get("latest_price_information") != "T-1 close":
        failures.append("H04/H05 context price cutoff drifted from T-1 close")
    if cutoff.get("allow_T_intraday_price_features") is not False:
        failures.append("T intraday context features are not forbidden")
    if cutoff.get("allow_T_close") is not False or cutoff.get("allow_T_plus_1") is not False:
        failures.append("future market data are not forbidden by preregistration")

    h05 = prereg.get("h05", {})
    if int(h05.get("group_formed_min_known_stocks", -1)) != 2:
        failures.append("H05 group minimum drifted from 2")
    if h05.get("breadth_condition") != "> 0.5":
        failures.append("H05 breadth condition drifted from > 0.5")
    if h05.get("candidate_core_condition") != "top quartile":
        failures.append("H05 candidate core condition drifted from top quartile")

    primary = prereg.get("primary_confluence", {})
    if primary.get("cluster_age") != ["FIRST_SEEN", "EARLY"]:
        failures.append("primary H04 age set drifted")
    if primary.get("group_formed") is not True:
        failures.append("primary confluence no longer requires GROUP_FORMED")
    if float(primary.get("positive_ratio_t1_gt", -1)) != 0.5:
        failures.append("primary breadth threshold drifted")
    if primary.get("candidate_top_quartile_t1") is not True:
        failures.append("primary confluence no longer requires top-quartile candidate")
    if primary.get("T_day_price_confirmation") is not False:
        failures.append("primary confluence permits T-day price confirmation")

    window = prereg.get("research_window", {})
    if unlock.get("research_window", {}).get("event_start") != window.get("event_start"):
        failures.append("unlock/prereg start mismatch")
    if unlock.get("research_window", {}).get("event_end") != window.get("event_end"):
        failures.append("unlock/prereg end mismatch")

    if failures:
        raise SystemExit(
            "H04/H05 locked before cluster/X02/market I/O: " + "; ".join(failures)
        )
    return unlock, prereg


def _artifact_path(raw: object, manifest_path: Path) -> Path:
    p = Path(str(raw or ""))
    if p.is_absolute() or p.exists():
        return p
    return manifest_path.parent / p


def validate_replay_inputs(
    replay_path: Path, assignments_path: Path, membership_path: Path, calendar_path: Path
) -> dict:
    replay = _json(replay_path)
    failures: list[str] = []
    if replay.get("validation", {}).get("pass") is not True:
        failures.append("cluster replay manifest did not PASS")
    if replay.get("market_blind") is not True or replay.get("x02_returns_read") is not False:
        failures.append("cluster replay is not market-blind")

    outputs = replay.get("outputs", {})
    expected = {
        assignments_path: outputs.get("assignments_sha256"),
        membership_path: outputs.get("membership_sha256"),
        calendar_path: replay.get("calendar", {}).get("sha256"),
    }
    declared = {
        assignments_path: _artifact_path(outputs.get("assignments"), replay_path),
        membership_path: _artifact_path(outputs.get("membership"), replay_path),
        calendar_path: _artifact_path(replay.get("calendar", {}).get("path"), replay_path),
    }
    for supplied, declared_path in declared.items():
        if supplied.resolve() != declared_path.resolve():
            failures.append(f"supplied artifact differs from replay manifest: {supplied}")
        if not supplied.exists():
            failures.append(f"missing replay artifact: {supplied}")
            continue
        expected_hash = expected[supplied]
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            failures.append(f"missing replay SHA-256 for {supplied}")
        elif _sha256_file(supplied) != expected_hash:
            failures.append(f"replay artifact hash mismatch: {supplied}")
    if failures:
        raise SystemExit("invalid V4.18-C replay inputs: " + "; ".join(failures))
    return replay


def load_cluster_inputs(
    assignments_path: Path, membership_path: Path, calendar_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int]]:
    assignments = pd.read_parquet(assignments_path)
    membership = pd.read_parquet(membership_path)
    calendar = pd.read_parquet(calendar_path)

    required_a = {
        "event_id", "instrument", "available_trade_date", "session_index", "cluster_id",
        "cluster_first_available_trade_date", "cluster_first_session_index", "builder_version",
    }
    required_m = {
        "cluster_id", "instrument", "member_first_available_trade_date",
        "member_first_session_index", "cluster_first_available_trade_date",
        "cluster_first_session_index", "builder_version",
    }
    required_c = {"trade_date", "calendar_sha256"}
    for name, frame, required in (
        ("assignments", assignments, required_a),
        ("membership", membership, required_m),
        ("calendar", calendar, required_c),
    ):
        missing = required - set(frame.columns)
        if missing:
            raise SystemExit(f"{name} missing required fields: {sorted(missing)}")
        if frame.empty:
            raise SystemExit(f"{name} is empty")

    if set(assignments["builder_version"].astype(str)) != {EXPECTED_CLUSTER_BUILDER}:
        raise SystemExit("unexpected cluster builder version in assignments")
    if set(membership["builder_version"].astype(str)) != {EXPECTED_CLUSTER_BUILDER}:
        raise SystemExit("unexpected cluster builder version in membership")

    dates = pd.to_datetime(calendar["trade_date"], errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise SystemExit("frozen calendar dates must be parseable, unique and increasing")
    days = dates.dt.date.astype(str).tolist()
    session_index = {day: i for i, day in enumerate(days)}
    return assignments, membership, calendar, session_index


def _novelty_bin(age: int | None) -> str:
    if age is None:
        return "NO_EVENT_CONTEXT"
    if age == 0:
        return "FIRST_SEEN"
    if age <= 5:
        return "EARLY"
    if age <= 20:
        return "RECENT"
    return "OLD"


def attach_event_context(
    candidates: pd.DataFrame,
    assignments: pd.DataFrame,
    membership: pd.DataFrame,
    session_index: dict[str, int],
    research_start: str,
) -> pd.DataFrame:
    """Attach exactly one causally visible event episode to each X02 candidate.

    Multi-context rule is frozen before outcomes: among clusters the instrument
    belongs to by T, select the cluster with the most recent event session <= T;
    ties are broken by lexical cluster_id. No price/return value participates.
    """
    x = candidates.copy()
    x["trade_date"] = pd.to_datetime(x["trade_date"]).dt.date.astype(str)
    x["signal_date"] = pd.to_datetime(x["signal_date"]).dt.date.astype(str)

    research_candidates = [idx for day, idx in session_index.items() if day >= research_start]
    if not research_candidates:
        raise SystemExit("research start is after frozen calendar")
    research_start_index = min(research_candidates)

    memberships_by_instrument: dict[str, list[tuple[int, str]]] = {}
    members_by_cluster: dict[str, list[tuple[int, str]]] = {}
    cluster_first: dict[str, int] = {}
    for row in membership.itertuples(index=False):
        cid = str(row.cluster_id)
        inst = str(row.instrument)
        first_idx = int(row.member_first_session_index)
        memberships_by_instrument.setdefault(inst, []).append((first_idx, cid))
        members_by_cluster.setdefault(cid, []).append((first_idx, inst))
        cluster_first[cid] = int(row.cluster_first_session_index)
    for values in memberships_by_instrument.values():
        values.sort()
    for values in members_by_cluster.values():
        values.sort()

    cluster_event_sessions: dict[str, list[int]] = {}
    for cid, group in assignments.groupby("cluster_id", sort=False):
        cluster_event_sessions[str(cid)] = sorted(
            pd.to_numeric(group["session_index"], errors="raise").astype(int).unique().tolist()
        )

    records: list[dict[str, Any]] = []
    for row in x.itertuples(index=False):
        base = row._asdict()
        trade_day = str(base["trade_date"])
        trade_idx = session_index.get(trade_day)
        if trade_idx is None:
            raise SystemExit(f"X02 trade date absent from frozen V4.18 calendar: {trade_day}")
        inst = str(base["instrument"])
        visible = [
            (first_idx, cid)
            for first_idx, cid in memberships_by_instrument.get(inst, [])
            if first_idx <= trade_idx
        ]
        options: list[tuple[int, str]] = []
        for _, cid in visible:
            sessions = cluster_event_sessions.get(cid, [])
            pos = bisect.bisect_right(sessions, trade_idx) - 1
            if pos >= 0:
                options.append((sessions[pos], cid))

        if not options:
            base.update({
                "context_cluster_id": None,
                "context_last_event_session_index": None,
                "context_last_event_trade_date": None,
                "context_age_trading_days": None,
                "h04_age_bin": "NO_EVENT_CONTEXT",
                "known_stock_count": 0,
                "group_formed": False,
                "burn_in_complete": trade_idx - research_start_index >= BURN_IN_SESSIONS,
                "_known_members": [],
            })
            records.append(base)
            continue

        latest_idx = max(v[0] for v in options)
        cid = min(v[1] for v in options if v[0] == latest_idx)
        first_idx = cluster_first[cid]
        age = trade_idx - first_idx
        known_members = [inst2 for idx2, inst2 in members_by_cluster[cid] if idx2 <= trade_idx]
        last_days = [day for day, idx in session_index.items() if idx == latest_idx]
        base.update({
            "context_cluster_id": cid,
            "context_last_event_session_index": latest_idx,
            "context_last_event_trade_date": last_days[0] if last_days else None,
            "context_age_trading_days": age,
            "h04_age_bin": _novelty_bin(age),
            "known_stock_count": len(known_members),
            "group_formed": len(known_members) >= 2,
            "burn_in_complete": trade_idx - research_start_index >= BURN_IN_SESSIONS,
            "_known_members": known_members,
        })
        records.append(base)
    return pd.DataFrame(records)


def _looks_like_lfs_pointer(path: Path) -> bool:
    try:
        return path.stat().st_size < 512 and b"git-lfs.github.com/spec/v1" in path.read_bytes()[:200]
    except OSError:
        return False


def _date_column(path: Path) -> str:
    names = set(pq.ParquetFile(path).schema.names)
    for col in ("date", "trade_date", "datetime", "time"):
        if col in names:
            return col
    raise ValueError(f"no date column in {path}")


def load_frozen_all_a_returns(
    daily_root: Path, needed: dict[str, set[str]]
) -> dict[tuple[str, str], float]:
    """Read only frozen T-1 daily data for event-group members.

    Supported source contracts are close/preclose, BaoStock pctChg, or a close
    series from which the one-session return can be reconstructed. Files are
    per-instrument and named INSTRUMENT.parquet.
    """
    if not daily_root.exists():
        raise FileNotFoundError(f"missing frozen BaoStock daily root: {daily_root}")
    out: dict[tuple[str, str], float] = {}
    for instrument in sorted(needed):
        dates_needed = needed[instrument]
        path = daily_root / f"{instrument}.parquet"
        if not path.exists():
            continue
        if _looks_like_lfs_pointer(path):
            raise RuntimeError(f"BaoStock daily file is still an LFS pointer: {path}")
        names = set(pq.ParquetFile(path).schema.names)
        date_col = _date_column(path)
        cols = [date_col, "close"]
        mode = "pct"
        pct_col = None
        if "preclose" in names:
            cols.append("preclose")
            mode = "preclose"
        elif "pctChg" in names:
            cols.append("pctChg")
            pct_col = "pctChg"
        elif "pct_chg" in names:
            cols.append("pct_chg")
            pct_col = "pct_chg"
        elif "close" not in names:
            raise RuntimeError(f"daily file lacks close/preclose/pctChg: {path}")
        else:
            mode = "close_series"
        frame = pd.read_parquet(path, columns=list(dict.fromkeys(cols)))
        days = pd.to_datetime(frame[date_col], errors="coerce").dt.date.astype(str)
        close = pd.to_numeric(frame["close"], errors="coerce")
        if mode == "preclose":
            pre = pd.to_numeric(frame["preclose"], errors="coerce")
            ret = close / pre.replace(0, np.nan) - 1.0
        elif mode == "pct":
            ret = pd.to_numeric(frame[pct_col], errors="coerce") / 100.0
        else:
            order = pd.to_datetime(frame[date_col], errors="coerce").sort_values().index
            temp = pd.DataFrame({"day": days, "close": close}).loc[order]
            temp["ret"] = temp["close"].pct_change(fill_method=None)
            days = temp["day"]
            ret = temp["ret"]
        for day, value in zip(days, ret):
            if day in dates_needed and pd.notna(value) and np.isfinite(float(value)):
                out[(instrument, day)] = float(value)
    return out


def add_h05_context(context: pd.DataFrame, returns: dict[tuple[str, str], float]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in context.to_dict("records"):
        members = [str(v) for v in row.get("_known_members", [])]
        signal_day = str(row["signal_date"])
        values = {m: returns[(m, signal_day)] for m in members if (m, signal_day) in returns}
        known = int(row.get("known_stock_count", 0))
        positive = sum(v > 0 for v in values.values())
        positive_ratio = positive / known if known else None
        candidate_return = values.get(str(row["instrument"]))
        top_quartile = False
        percentile = None
        if candidate_return is not None and len(values) >= 2:
            s = pd.Series(values, dtype=float)
            ranks = s.rank(method="average", pct=True)
            percentile = float(ranks.loc[str(row["instrument"])])
            top_quartile = percentile >= 0.75
        row.update({
            "priced_stock_count_t1": len(values),
            "missing_stock_count_t1": max(0, known - len(values)),
            # Missing/suspended known members contribute zero positives to the
            # literal fraction of causally known members; this is conservative.
            "positive_ratio_t1": positive_ratio,
            "candidate_return_t1": candidate_return,
            "candidate_group_return_percentile_t1": percentile,
            "candidate_top_quartile_t1": bool(top_quartile),
        })
        row["primary_confluence"] = bool(
            row.get("burn_in_complete", False)
            and row.get("h04_age_bin") in {"FIRST_SEEN", "EARLY"}
            and row.get("group_formed", False)
            and positive_ratio is not None
            and positive_ratio > 0.5
            and top_quartile
        )
        row.pop("_known_members", None)
        rows.append(row)
    return pd.DataFrame(rows)


def needed_group_returns(context: pd.DataFrame) -> dict[str, set[str]]:
    needed: dict[str, set[str]] = {}
    for row in context.to_dict("records"):
        day = str(row["signal_date"])
        for inst in row.get("_known_members", []):
            needed.setdefault(str(inst), set()).add(day)
    return needed


def _period_result(v43: Any, series: pd.Series, ledger: pd.DataFrame, start: str, end: str) -> dict:
    s, l = v43._slice(series, ledger, pd.Timestamp(start), pd.Timestamp(end))
    metrics = v43._metrics(s, l)
    active = s[s.ne(0)].sort_values(ascending=False)
    remove_n = int(math.ceil(len(active) * 0.05)) if len(active) else 0
    ablated = s.copy()
    if remove_n:
        ablated.loc[active.index[:remove_n]] = 0.0
    ablated_metrics = v43._metrics(ablated, l[~l["trade_date"].isin(active.index[:remove_n])].copy())
    n_days = int(metrics.get("n_days", 0) or 0)
    active_days = int(metrics.get("active_days", 0) or 0)
    metrics["best_5pct_active_days_removed"] = remove_n
    metrics["best_5pct_ablation_cagr"] = ablated_metrics.get("cagr")
    metrics["annualized_one_way_turnover"] = (active_days / n_days * 252.0) if n_days else None
    metrics["annualized_round_trip_turnover"] = (2.0 * active_days / n_days * 252.0) if n_days else None
    return metrics


def evaluate_sample(v43: Any, sample: pd.DataFrame, all_dates: list[pd.Timestamp], prereg: dict) -> dict:
    x = sample.copy()
    if not x.empty:
        x["score"] = pd.to_numeric(x["clean_mom20_rank"], errors="coerce").fillna(-np.inf)
        x = v43._select_top(x, TOP_N)
    window = prereg["research_window"]
    dev_start, dev_end = window["development"]
    later_start, later_end = window["later_period"]
    out: dict[str, Any] = {"selected_rows": int(len(x)), "costs": {}}
    for cost in COST_NAMES:
        series, ledger = v43._portfolio_series(x, all_dates, EXIT_LABEL, cost)
        out["costs"][cost] = {
            "development_2021_2023": _period_result(v43, series, ledger, dev_start, dev_end),
            "later_2024_2026": _period_result(v43, series, ledger, later_start, later_end),
        }
    return out


def _formal_pass(primary: dict) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for cost in COST_NAMES:
        periods = primary["costs"].get(cost, {})
        for period in ("development_2021_2023", "later_2024_2026"):
            m = periods.get(period, {})
            cagr = m.get("cagr")
            ablated = m.get("best_5pct_ablation_cagr")
            active = int(m.get("active_days", 0) or 0)
            if active < 20:
                failures.append(f"{cost} {period}: active_days {active} < 20")
            if cagr is None or (cagr <= 0 if cost == "BASE" else cagr < 0):
                failures.append(f"{cost} {period}: CAGR sign criterion failed")
            if ablated is None or (ablated <= 0 if cost == "BASE" else ablated < 0):
                failures.append(f"{cost} {period}: depends on best 5% active days")
    return not failures, failures


def run_formal(paths: Paths, unlock: dict, prereg: dict) -> dict:
    # From this line onward market I/O is allowed because the control plane passed.
    replay = validate_replay_inputs(paths.replay_manifest, paths.assignments, paths.membership, paths.calendar)
    assignments, membership, calendar, session_index = load_cluster_inputs(
        paths.assignments, paths.membership, paths.calendar
    )

    # Deferred imports make the no-market-I/O-before-unlock boundary structural.
    import v4_3_long_only_portfolio as v43

    candidates, all_dates = v43._prepare_candidates()
    minute = v43._minute_extract(candidates)
    features = v43._add_intraday_features(candidates, minute)
    eligible = features[
        features["base_executable"] & features["limit_gap"].ge(LIMIT_BUFFER)
    ].copy()

    window = prereg["research_window"]
    start = str(window["event_start"])
    end = str(window["event_end"])
    eligible = eligible[
        (pd.to_datetime(eligible["trade_date"]) >= pd.Timestamp(start))
        & (pd.to_datetime(eligible["trade_date"]) <= pd.Timestamp(end))
    ].copy()
    all_dates = [d for d in all_dates if pd.Timestamp(start) <= d <= pd.Timestamp(end)]

    context = attach_event_context(eligible, assignments, membership, session_index, start)
    needed = needed_group_returns(context)
    frozen_returns = load_frozen_all_a_returns(paths.daily_root, needed)
    context = add_h05_context(context, frozen_returns)

    # H04 labels are not performance-eligible inside the frozen 60-session burn-in.
    context = context[context["burn_in_complete"]].copy()
    if context.empty:
        raise SystemExit("no X02 candidates remain after the preregistered burn-in")
    first_trade = pd.Timestamp(context["trade_date"].min())
    all_dates = [d for d in all_dates if d >= first_trade]

    baseline = evaluate_sample(v43, context, all_dates, prereg)
    primary_rows = context[context["primary_confluence"]].copy()
    primary = evaluate_sample(v43, primary_rows, all_dates, prereg)
    passed, failures = _formal_pass(primary)

    paths.ledger.parent.mkdir(parents=True, exist_ok=True)
    context.sort_values(["trade_date", "instrument"]).to_csv(paths.ledger, index=False)

    report = {
        "runner_version": RUNNER_VERSION,
        "scientific_status": "FIRST_FORMAL_PREREGISTERED_TEST_COMPLETE",
        "prereg_version": prereg.get("prereg_version"),
        "unlock_gate_version": unlock.get("gate_version"),
        "research_window": window,
        "parameter_search_performed": False,
        "market_io_started_only_after_unlock": True,
        "execution": {
            "signal": "X02_limit_adjusted_momentum fixed on T-1 close",
            "selected_rule": "raw_mom20_rank>=0.80 & clean_mom20_rank>=0.80 & hit_count20<=1",
            "limit_buffer": LIMIT_BUFFER,
            "rank": "clean_mom20_rank",
            "top_n": TOP_N,
            "entry": "T 14:45 completed 5m close",
            "exit": "T+1 10:00",
            "costs": list(COST_NAMES),
            "T_day_context_price_confirmation": False,
        },
        "event_context": {
            "multi_context_selection": "latest event session <= T among candidate memberships; lexical cluster_id tie-break",
            "age_origin": "cluster_first_session_index",
            "group_membership": "member_first_session_index <= T",
            "h05_market_cutoff": "T-1 daily bar only",
            "h05_daily_source": str(paths.daily_root),
            "missing_member_return_policy": "known member with no T-1 return contributes zero positives; candidate core rank uses priced members only",
            "candidate_core_rank": "ascending average percentile >= 0.75",
        },
        "replay": {
            "manifest": str(paths.replay_manifest),
            "assignments_sha256": replay.get("outputs", {}).get("assignments_sha256"),
            "membership_sha256": replay.get("outputs", {}).get("membership_sha256"),
            "calendar_sha256": replay.get("calendar", {}).get("calendar_sha256"),
        },
        "coverage": {
            "x02_executable_candidate_rows_after_burn_in": int(len(context)),
            "x02_executable_candidate_dates_after_burn_in": int(context["trade_date"].nunique()),
            "with_event_context_rows": int(context["context_cluster_id"].notna().sum()),
            "primary_confluence_candidate_rows": int(len(primary_rows)),
            "primary_confluence_candidate_dates": int(primary_rows["trade_date"].nunique()) if len(primary_rows) else 0,
            "retained_X02_opportunity_fraction": float(len(primary_rows) / len(context)) if len(context) else 0.0,
        },
        "baseline_same_fixed_X02_without_event_context": baseline,
        "primary_confluence": primary,
        "falsification": {
            "rule": "BASE CAGR >0 and CONSERVATIVE CAGR >=0 in both periods; >=20 active days per period; same sign criteria must survive removal of best 5% active days",
            "pass": passed,
            "failures": failures,
        },
        "interpretation_rule": (
            "Only the preregistered primary confluence is confirmatory. H04 age partitions and H05 axes "
            "may be reported descriptively but cannot replace the primary rule after outcomes are seen."
        ),
    }
    paths.output.parent.mkdir(parents=True, exist_ok=True)
    paths.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"coverage": report["coverage"], "falsification": report["falsification"]}, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    args = parse_args()
    paths = Paths(
        prereg=Path(args.prereg), unlock=Path(args.unlock), replay_manifest=Path(args.replay_manifest),
        assignments=Path(args.assignments), membership=Path(args.membership), calendar=Path(args.calendar),
        daily_root=Path(args.daily_root), output=Path(args.output), ledger=Path(args.ledger),
    )
    # This call MUST remain before all research-data reads/imports.
    unlock, prereg = validate_control_plane(paths.unlock, paths.prereg)
    run_formal(paths, unlock, prereg)


if __name__ == "__main__":
    main()
