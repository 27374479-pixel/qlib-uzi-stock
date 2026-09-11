#!/usr/bin/env python3
"""First formal preregistered H04/H05 performance test.

Control-plane rule: unlock + preregistration + runner contract are validated
before cluster, X02, price, return, P&L, daily, or minute research data are read.
The first formal test then reuses the frozen V4.16/V4.3 X02 execution exactly and
adds only the preregistered point-in-time event context.
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

RUNNER_VERSION = "v4.18-h04-h05-runner.2"
EXPECTED_UNLOCK_VERSION = "v4.18-h04-h05-unlock.1"
EXPECTED_PREREG_VERSION = "v4.18-h04-h05-prereg.1"
EXPECTED_CONTRACT_VERSION = "v4.18-h04-h05-runner-contract.1"
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
    runner_contract: Path
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
    p.add_argument("--runner-contract", default="v4_18_h04_h05_runner_contract_v1.json")
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
        raise SystemExit(f"missing required control/evidence artifact: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"cannot parse JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"JSON artifact must be an object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_control_plane(
    unlock_path: Path, prereg_path: Path, contract_path: Path
) -> tuple[dict, dict, dict]:
    """Must be the first data-dependent action in main()."""
    unlock = _json(unlock_path)
    prereg = _json(prereg_path)
    contract = _json(contract_path)
    failures: list[str] = []

    exp = unlock.get("experiment_unlock", {})
    if unlock.get("gate_version") != EXPECTED_UNLOCK_VERSION:
        failures.append("unexpected unlock gate version")
    if unlock.get("scientific_status") != "READY_FOR_FIRST_FORMAL_H04_H05_TEST":
        failures.append("unlock scientific_status is not READY_FOR_FIRST_FORMAL_H04_H05_TEST")
    if unlock.get("validation", {}).get("pass") is not True:
        failures.append("unlock validation.pass is not true")
    if exp.get("h04_h05_allowed") is not True:
        failures.append("unlock does not allow H04/H05")
    if exp.get("parameter_search_in_primary_test_allowed") is not False:
        failures.append("unlock does not forbid primary-test parameter search")

    if prereg.get("prereg_version") != EXPECTED_PREREG_VERSION:
        failures.append("unexpected preregistration version")
    if prereg.get("scientific_status") != "PREREGISTERED_NOT_TESTED":
        failures.append("preregistration is not PREREGISTERED_NOT_TESTED")
    if prereg.get("parameter_search_in_primary_test_allowed") is not False:
        failures.append("preregistration permits primary-test parameter search")

    if contract.get("runner_contract_version") != EXPECTED_CONTRACT_VERSION:
        failures.append("unexpected runner-contract version")
    if contract.get("scientific_status") != "FROZEN_BEFORE_FIRST_FORMAL_RESULT":
        failures.append("runner contract is not frozen before first result")
    if contract.get("required_unlock_gate_version") != EXPECTED_UNLOCK_VERSION:
        failures.append("runner contract unlock version mismatch")
    if contract.get("market_io_before_unlock_allowed") is not False:
        failures.append("runner contract permits market I/O before unlock")
    if contract.get("parameter_search_allowed") is not False:
        failures.append("runner contract permits parameter search")

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

    cx = contract.get("x02", {})
    if cx.get("execution_limit_buffer") != LIMIT_BUFFER:
        failures.append("runner limit buffer drift")
    if cx.get("ranking") != "clean_mom20_rank" or cx.get("top_n") != TOP_N:
        failures.append("runner ranking/TopN drift")
    if cx.get("exit") != "T+1 10:00 completed 5m close":
        failures.append("runner exit drift")
    if cx.get("cost_models") != list(COST_NAMES):
        failures.append("runner cost models drift")
    if cx.get("T_day_context_price_confirmation") is not False:
        failures.append("runner contract permits T-day context confirmation")

    cutoff = prereg.get("first_test_market_cutoff", {})
    if cutoff.get("latest_price_information") != "T-1 close":
        failures.append("H04/H05 market cutoff drifted from T-1 close")
    if cutoff.get("allow_T_intraday_price_features") is not False:
        failures.append("T intraday context features are not forbidden")
    if cutoff.get("allow_T_close") is not False or cutoff.get("allow_T_plus_1") is not False:
        failures.append("future market data are not forbidden")

    h05 = prereg.get("h05", {})
    if int(h05.get("group_formed_min_known_stocks", -1)) != 2:
        failures.append("H05 group minimum drifted")
    if h05.get("breadth_condition") != "> 0.5":
        failures.append("H05 breadth threshold drifted")
    if h05.get("candidate_core_condition") != "top quartile":
        failures.append("H05 core definition drifted")

    primary = prereg.get("primary_confluence", {})
    if primary.get("cluster_age") != ["FIRST_SEEN", "EARLY"]:
        failures.append("primary H04 age set drifted")
    if primary.get("group_formed") is not True:
        failures.append("primary confluence lost GROUP_FORMED")
    if float(primary.get("positive_ratio_t1_gt", -1)) != 0.5:
        failures.append("primary breadth threshold drifted")
    if primary.get("candidate_top_quartile_t1") is not True:
        failures.append("primary confluence lost candidate core")
    if primary.get("T_day_price_confirmation") is not False:
        failures.append("primary confluence permits T-day confirmation")

    window = prereg.get("research_window", {})
    if unlock.get("research_window", {}).get("event_start") != window.get("event_start"):
        failures.append("unlock/prereg start mismatch")
    if unlock.get("research_window", {}).get("event_end") != window.get("event_end"):
        failures.append("unlock/prereg end mismatch")
    cf = contract.get("falsification", {}).get("periods", {})
    if cf.get("development") != window.get("development") or cf.get("later") != window.get("later_period"):
        failures.append("runner contract/prereg period mismatch")

    if failures:
        raise SystemExit(
            "H04/H05 locked before cluster/X02/market I/O: " + "; ".join(failures)
        )
    return unlock, prereg, contract


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
    specs = [
        (assignments_path, outputs.get("assignments"), outputs.get("assignments_sha256"), "assignments"),
        (membership_path, outputs.get("membership"), outputs.get("membership_sha256"), "membership"),
        (calendar_path, replay.get("calendar", {}).get("path"), replay.get("calendar", {}).get("sha256"), "calendar"),
    ]
    for supplied, raw_declared, expected_hash, label in specs:
        declared = _artifact_path(raw_declared, replay_path)
        if supplied.resolve() != declared.resolve():
            failures.append(f"supplied {label} differs from replay manifest")
        if not supplied.exists():
            failures.append(f"missing replay artifact: {supplied}")
            continue
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            failures.append(f"missing replay SHA-256 for {label}")
        elif _sha256_file(supplied) != expected_hash:
            failures.append(f"replay artifact hash mismatch: {label}")
    if failures:
        raise SystemExit("invalid V4.18-C replay inputs: " + "; ".join(failures))
    return replay


def load_cluster_inputs(
    assignments_path: Path, membership_path: Path, calendar_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, int], dict[int, str]]:
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
    for name, frame, required in (
        ("assignments", assignments, required_a),
        ("membership", membership, required_m),
    ):
        missing = required - set(frame.columns)
        if missing or frame.empty:
            raise SystemExit(f"{name} invalid; missing={sorted(missing)} rows={len(frame)}")
    if {"trade_date", "calendar_sha256"} - set(calendar.columns) or calendar.empty:
        raise SystemExit("frozen calendar missing required fields or empty")
    if set(assignments["builder_version"].astype(str)) != {EXPECTED_CLUSTER_BUILDER}:
        raise SystemExit("unexpected cluster builder version in assignments")
    if set(membership["builder_version"].astype(str)) != {EXPECTED_CLUSTER_BUILDER}:
        raise SystemExit("unexpected cluster builder version in membership")

    dates = pd.to_datetime(calendar["trade_date"], errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise SystemExit("frozen calendar dates must be parseable, unique and increasing")
    days = dates.dt.date.astype(str).tolist()
    session_index = {day: i for i, day in enumerate(days)}
    index_date = {i: day for day, i in session_index.items()}
    return assignments, membership, calendar, session_index, index_date


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
    """Attach one context using event chronology only; preserve market date types."""
    x = candidates.copy()
    x["trade_date"] = pd.to_datetime(x["trade_date"]).dt.normalize()
    x["signal_date"] = pd.to_datetime(x["signal_date"]).dt.normalize()
    research_indices = [idx for day, idx in session_index.items() if day >= research_start]
    if not research_indices:
        raise SystemExit("research start is after frozen calendar")
    research_start_index = min(research_indices)
    index_date = {idx: day for day, idx in session_index.items()}

    memberships_by_instrument: dict[str, list[tuple[int, str]]] = {}
    members_by_cluster: dict[str, list[tuple[int, str]]] = {}
    cluster_first: dict[str, int] = {}
    for row in membership.itertuples(index=False):
        cid, inst = str(row.cluster_id), str(row.instrument)
        first_idx = int(row.member_first_session_index)
        memberships_by_instrument.setdefault(inst, []).append((first_idx, cid))
        members_by_cluster.setdefault(cid, []).append((first_idx, inst))
        cluster_first[cid] = int(row.cluster_first_session_index)
    for values in memberships_by_instrument.values():
        values.sort()
    for values in members_by_cluster.values():
        values.sort()

    event_sessions = {
        str(cid): sorted(pd.to_numeric(group["session_index"], errors="raise").astype(int).unique().tolist())
        for cid, group in assignments.groupby("cluster_id", sort=False)
    }

    records: list[dict[str, Any]] = []
    for row in x.to_dict("records"):
        base = dict(row)
        trade_day = pd.Timestamp(base["trade_date"]).date().isoformat()
        trade_idx = session_index.get(trade_day)
        if trade_idx is None:
            raise SystemExit(f"X02 trade date absent from frozen V4.18 calendar: {trade_day}")
        inst = str(base["instrument"])
        options: list[tuple[int, str]] = []
        for first_idx, cid in memberships_by_instrument.get(inst, []):
            if first_idx > trade_idx:
                continue
            sessions = event_sessions.get(cid, [])
            pos = bisect.bisect_right(sessions, trade_idx) - 1
            if pos >= 0:
                options.append((sessions[pos], cid))

        burn = trade_idx - research_start_index >= BURN_IN_SESSIONS
        if not options:
            base.update({
                "context_cluster_id": None,
                "context_last_event_session_index": None,
                "context_last_event_trade_date": None,
                "context_age_trading_days": None,
                "h04_age_bin": "NO_EVENT_CONTEXT",
                "known_stock_count": 0,
                "group_formed": False,
                "burn_in_complete": burn,
                "_known_members": [],
            })
            records.append(base)
            continue

        latest_idx = max(value[0] for value in options)
        cid = min(value[1] for value in options if value[0] == latest_idx)
        first_idx = cluster_first[cid]
        age = trade_idx - first_idx
        known_members = sorted({
            member for member_idx, member in members_by_cluster[cid] if member_idx <= trade_idx
        })
        base.update({
            "context_cluster_id": cid,
            "context_last_event_session_index": latest_idx,
            "context_last_event_trade_date": index_date.get(latest_idx),
            "context_age_trading_days": age,
            "h04_age_bin": _novelty_bin(age),
            "known_stock_count": len(known_members),
            "group_formed": len(known_members) >= 2,
            "burn_in_complete": burn,
            "_known_members": known_members,
        })
        records.append(base)
    out = pd.DataFrame(records)
    if not out.empty:
        out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.normalize()
        out["signal_date"] = pd.to_datetime(out["signal_date"]).dt.normalize()
    return out


def _looks_like_lfs_pointer(path: Path) -> bool:
    try:
        return path.stat().st_size < 512 and b"git-lfs.github.com/spec/v1" in path.read_bytes()[:200]
    except OSError:
        return False


def _date_column(path: Path, names: set[str]) -> str:
    for col in ("date", "trade_date", "datetime", "time"):
        if col in names:
            return col
    raise RuntimeError(f"no date column in {path}")


def load_frozen_all_a_returns(
    daily_root: Path, needed: dict[str, set[str]]
) -> dict[tuple[str, str], float]:
    """Load only frozen all-A-share T-1 returns needed by candidate clusters."""
    if not daily_root.exists():
        raise FileNotFoundError(f"missing frozen BaoStock daily root: {daily_root}")
    out: dict[tuple[str, str], float] = {}
    for instrument in sorted(needed):
        path = daily_root / f"{instrument}.parquet"
        if not path.exists():
            continue
        if _looks_like_lfs_pointer(path):
            raise RuntimeError(f"BaoStock daily file is still an LFS pointer: {path}")
        names = set(pq.ParquetFile(path).schema.names)
        date_col = _date_column(path, names)
        if {"close", "preclose"}.issubset(names):
            mode, cols = "preclose", [date_col, "close", "preclose"]
        elif "pctChg" in names:
            mode, cols = "pctChg", [date_col, "pctChg"]
        elif "pct_chg" in names:
            mode, cols = "pct_chg", [date_col, "pct_chg"]
        elif "close" in names:
            mode, cols = "close_series", [date_col, "close"]
        else:
            raise RuntimeError(f"daily file lacks return-compatible fields: {path}")
        frame = pd.read_parquet(path, columns=cols)
        dt = pd.to_datetime(frame[date_col], errors="coerce")
        if mode == "preclose":
            close = pd.to_numeric(frame["close"], errors="coerce")
            pre = pd.to_numeric(frame["preclose"], errors="coerce")
            ret = close / pre.replace(0, np.nan) - 1.0
            days = dt.dt.date.astype(str)
        elif mode in {"pctChg", "pct_chg"}:
            ret = pd.to_numeric(frame[mode], errors="coerce") / 100.0
            days = dt.dt.date.astype(str)
        else:
            temp = pd.DataFrame({"dt": dt, "close": pd.to_numeric(frame["close"], errors="coerce")})
            temp = temp.dropna(subset=["dt"]).sort_values("dt")
            temp["ret"] = temp["close"].pct_change(fill_method=None)
            days = temp["dt"].dt.date.astype(str)
            ret = temp["ret"]
        wanted = needed[instrument]
        for day, value in zip(days, ret):
            if day in wanted and pd.notna(value) and np.isfinite(float(value)):
                out[(instrument, day)] = float(value)
    return out


def needed_group_returns(context: pd.DataFrame) -> dict[str, set[str]]:
    needed: dict[str, set[str]] = {}
    for row in context.to_dict("records"):
        day = pd.Timestamp(row["signal_date"]).date().isoformat()
        for instrument in row.get("_known_members", []):
            needed.setdefault(str(instrument), set()).add(day)
    return needed


def add_h05_context(
    context: pd.DataFrame, returns: dict[tuple[str, str], float]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for source in context.to_dict("records"):
        row = dict(source)
        members = [str(value) for value in row.get("_known_members", [])]
        signal_day = pd.Timestamp(row["signal_date"]).date().isoformat()
        values = {
            member: returns[(member, signal_day)]
            for member in members if (member, signal_day) in returns
        }
        known = int(row.get("known_stock_count", 0))
        positive_ratio = (sum(value > 0 for value in values.values()) / known) if known else None
        instrument = str(row["instrument"])
        candidate_return = values.get(instrument)
        percentile: float | None = None
        top_quartile = False
        if candidate_return is not None and len(values) >= 2:
            ranks = pd.Series(values, dtype=float).rank(method="average", pct=True)
            percentile = float(ranks.loc[instrument])
            top_quartile = percentile >= 0.75
        row.update({
            "priced_stock_count_t1": len(values),
            "missing_stock_count_t1": max(0, known - len(values)),
            "positive_ratio_t1": positive_ratio,
            "candidate_return_t1": candidate_return,
            "candidate_group_return_percentile_t1": percentile,
            "candidate_top_quartile_t1": bool(top_quartile),
        })
        row["primary_confluence"] = bool(
            row.get("burn_in_complete", False)
            and row.get("h04_age_bin") in {"FIRST_SEEN", "EARLY"}
            and row.get("group_formed", False)
            and positive_ratio is not None and positive_ratio > 0.5
            and top_quartile
        )
        row.pop("_known_members", None)
        rows.append(row)
    out = pd.DataFrame(rows)
    if not out.empty:
        out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.normalize()
        out["signal_date"] = pd.to_datetime(out["signal_date"]).dt.normalize()
    return out


def _period_result(
    v43: Any, series: pd.Series, ledger: pd.DataFrame, start: str, end: str
) -> dict[str, Any]:
    s, l = v43._slice(series, ledger, pd.Timestamp(start), pd.Timestamp(end))
    metrics = v43._metrics(s, l)
    active = s[s.ne(0)].sort_values(ascending=False)
    remove_n = int(math.ceil(len(active) * 0.05)) if len(active) else 0
    removed_dates = active.index[:remove_n]
    ablated = s.copy()
    if remove_n:
        ablated.loc[removed_dates] = 0.0
    ablated_ledger = l[~pd.to_datetime(l["trade_date"]).isin(removed_dates)].copy() if not l.empty else l
    ablated_metrics = v43._metrics(ablated, ablated_ledger)
    n_days = int(metrics.get("n_days", 0) or 0)
    active_days = int(metrics.get("active_days", 0) or 0)
    metrics.update({
        "best_5pct_active_days_removed": remove_n,
        "best_5pct_ablation_cagr": ablated_metrics.get("cagr"),
        "annualized_one_way_turnover": (active_days / n_days * 252.0) if n_days else None,
        "annualized_round_trip_turnover": (2.0 * active_days / n_days * 252.0) if n_days else None,
    })
    return metrics


def evaluate_sample(
    v43: Any, sample: pd.DataFrame, all_dates: list[pd.Timestamp], prereg: dict
) -> dict[str, Any]:
    x = sample.copy()
    if "trade_date" in x.columns:
        x["trade_date"] = pd.to_datetime(x["trade_date"]).dt.normalize()
    if not x.empty:
        x["score"] = pd.to_numeric(x["clean_mom20_rank"], errors="coerce").fillna(-np.inf)
        x = v43._select_top(x, TOP_N)
    window = prereg["research_window"]
    dev_start, dev_end = window["development"]
    later_start, later_end = window["later_period"]
    out: dict[str, Any] = {"selected_rows": int(len(x)), "selected_dates": int(x["trade_date"].nunique()) if len(x) else 0, "costs": {}}
    for cost in COST_NAMES:
        series, ledger = v43._portfolio_series(x, all_dates, EXIT_LABEL, cost)
        out["costs"][cost] = {
            "development_2021_2023": _period_result(v43, series, ledger, dev_start, dev_end),
            "later_2024_2026": _period_result(v43, series, ledger, later_start, later_end),
        }
    return out


def evaluate_fixed_partitions(
    v43: Any, context: pd.DataFrame, all_dates: list[pd.Timestamp], prereg: dict
) -> dict[str, Any]:
    """Required descriptive cells; none may replace the primary confirmatory rule."""
    age_labels = ["NO_EVENT_CONTEXT", "FIRST_SEEN", "EARLY", "RECENT", "OLD"]
    result: dict[str, Any] = {"h04_age": {}, "group_formed": {}, "breadth": {}, "candidate_core": {}}
    for label in age_labels:
        result["h04_age"][label] = evaluate_sample(
            v43, context[context["h04_age_bin"].eq(label)].copy(), all_dates, prereg
        )
    result["group_formed"]["NOT_FORMED"] = evaluate_sample(
        v43, context[~context["group_formed"].fillna(False)].copy(), all_dates, prereg
    )
    result["group_formed"]["GROUP_FORMED"] = evaluate_sample(
        v43, context[context["group_formed"].fillna(False)].copy(), all_dates, prereg
    )
    breadth = pd.to_numeric(context["positive_ratio_t1"], errors="coerce")
    result["breadth"]["LE_0_5"] = evaluate_sample(
        v43, context[breadth.notna() & breadth.le(0.5)].copy(), all_dates, prereg
    )
    result["breadth"]["GT_0_5"] = evaluate_sample(
        v43, context[breadth.gt(0.5)].copy(), all_dates, prereg
    )
    core = context["candidate_top_quartile_t1"].fillna(False).astype(bool)
    result["candidate_core"]["NOT_TOP_QUARTILE"] = evaluate_sample(
        v43, context[~core].copy(), all_dates, prereg
    )
    result["candidate_core"]["TOP_QUARTILE"] = evaluate_sample(
        v43, context[core].copy(), all_dates, prereg
    )
    return result


def _formal_pass(primary: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for cost in COST_NAMES:
        for period in ("development_2021_2023", "later_2024_2026"):
            metrics = primary["costs"].get(cost, {}).get(period, {})
            cagr = metrics.get("cagr")
            ablated = metrics.get("best_5pct_ablation_cagr")
            active_days = int(metrics.get("active_days", 0) or 0)
            if active_days < 20:
                failures.append(f"{cost} {period}: active_days {active_days} < 20")
            bad_cagr = cagr is None or (cagr <= 0 if cost == "BASE" else cagr < 0)
            bad_ablated = ablated is None or (ablated <= 0 if cost == "BASE" else ablated < 0)
            if bad_cagr:
                failures.append(f"{cost} {period}: CAGR sign criterion failed")
            if bad_ablated:
                failures.append(f"{cost} {period}: best-5%-day ablation sign criterion failed")
    return not failures, failures


def run_formal(paths: Paths, unlock: dict, prereg: dict, contract: dict) -> dict[str, Any]:
    replay = validate_replay_inputs(
        paths.replay_manifest, paths.assignments, paths.membership, paths.calendar
    )
    assignments, membership, _, session_index, index_date = load_cluster_inputs(
        paths.assignments, paths.membership, paths.calendar
    )

    window = prereg["research_window"]
    start, end = str(window["event_start"]), str(window["event_end"])
    research_indices = [idx for day, idx in session_index.items() if day >= start]
    if not research_indices:
        raise SystemExit("research start is after frozen calendar")
    burn_index = min(research_indices) + BURN_IN_SESSIONS
    if burn_index not in index_date:
        raise SystemExit("frozen calendar is too short for preregistered burn-in")
    burn_day = pd.Timestamp(index_date[burn_index])

    # Deferred import: importing/executing X02 code is impossible before control-plane PASS.
    import v4_3_long_only_portfolio as v43

    candidates, all_dates = v43._prepare_candidates()
    candidates["trade_date"] = pd.to_datetime(candidates["trade_date"]).dt.normalize()
    candidates = candidates[
        candidates["trade_date"].between(max(pd.Timestamp(start), burn_day), pd.Timestamp(end))
    ].copy()
    all_dates = [
        pd.Timestamp(day).normalize() for day in all_dates
        if max(pd.Timestamp(start), burn_day) <= pd.Timestamp(day) <= pd.Timestamp(end)
    ]
    minute = v43._minute_extract(candidates)
    features = v43._add_intraday_features(candidates, minute)
    eligible = features[
        features["base_executable"] & features["limit_gap"].ge(LIMIT_BUFFER)
    ].copy()

    context = attach_event_context(eligible, assignments, membership, session_index, start)
    context = context[context["burn_in_complete"]].copy()
    frozen_returns = load_frozen_all_a_returns(paths.daily_root, needed_group_returns(context))
    context = add_h05_context(context, frozen_returns)
    if context.empty:
        raise SystemExit("no X02 candidates remain after the preregistered burn-in")

    baseline = evaluate_sample(v43, context, all_dates, prereg)
    primary_rows = context[context["primary_confluence"]].copy()
    primary = evaluate_sample(v43, primary_rows, all_dates, prereg)
    descriptive = evaluate_fixed_partitions(v43, context, all_dates, prereg)
    passed, failures = _formal_pass(primary)

    paths.ledger.parent.mkdir(parents=True, exist_ok=True)
    context.sort_values(["trade_date", "instrument"]).to_csv(paths.ledger, index=False)
    selected_retention = (
        float(primary["selected_rows"] / baseline["selected_rows"])
        if baseline["selected_rows"] else 0.0
    )

    report = {
        "runner_version": RUNNER_VERSION,
        "scientific_status": "FIRST_FORMAL_PREREGISTERED_TEST_COMPLETE",
        "prereg_version": prereg.get("prereg_version"),
        "runner_contract_version": contract.get("runner_contract_version"),
        "runner_contract_sha256": _sha256_file(paths.runner_contract),
        "unlock_gate_version": unlock.get("gate_version"),
        "research_window": window,
        "effective_performance_start_after_burn_in": str(burn_day.date()),
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
            "cost_specs": {
                name: {
                    "commission_each_side": float(v43.COSTS[name].commission_each_side),
                    "slippage_each_side": float(v43.COSTS[name].slippage_each_side),
                } for name in COST_NAMES
            },
            "stamp_duty": "reuse v4_3 historical sell-side stamp duty",
            "T_day_context_price_confirmation": False,
        },
        "event_context": {
            "multi_context_selection": "latest cluster event session <= T; lexical cluster_id tie-break",
            "age_origin": "cluster_first_session_index",
            "group_membership": "member_first_session_index <= T",
            "h05_market_cutoff": "T-1 completed daily bar only",
            "h05_daily_source": str(paths.daily_root),
            "positive_ratio_denominator": "all causally known group members",
            "missing_member_return_policy": "missing/suspended member gets zero positive credit",
            "candidate_core_rank": "ascending average percentile among priced known members; >=0.75",
        },
        "replay": {
            "manifest": str(paths.replay_manifest),
            "assignments_sha256": replay.get("outputs", {}).get("assignments_sha256"),
            "membership_sha256": replay.get("outputs", {}).get("membership_sha256"),
            "calendar_sha256": replay.get("calendar", {}).get("calendar_sha256"),
        },
        "coverage": {
            "x02_executable_candidate_rows": int(len(context)),
            "x02_executable_candidate_dates": int(context["trade_date"].nunique()),
            "with_event_context_rows": int(context["context_cluster_id"].notna().sum()),
            "primary_confluence_candidate_rows": int(len(primary_rows)),
            "primary_confluence_candidate_dates": int(primary_rows["trade_date"].nunique()) if len(primary_rows) else 0,
            "retained_X02_candidate_fraction": float(len(primary_rows) / len(context)) if len(context) else 0.0,
            "retained_X02_selected_trade_row_fraction": selected_retention,
        },
        "baseline_same_fixed_X02_without_event_context": baseline,
        "primary_confluence": primary,
        "required_descriptive_partitions": descriptive,
        "falsification": {
            "rule": "both periods: BASE CAGR >0; CONSERVATIVE CAGR >=0; >=20 active days; same sign criteria after removing best 5% active days",
            "pass": passed,
            "failures": failures,
        },
        "interpretation_rule": (
            "Only the preregistered primary confluence is confirmatory. Fixed descriptive partitions "
            "cannot replace it after outcomes are observed."
        ),
    }
    paths.output.parent.mkdir(parents=True, exist_ok=True)
    paths.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"coverage": report["coverage"], "falsification": report["falsification"]}, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    args = parse_args()
    paths = Paths(
        prereg=Path(args.prereg),
        unlock=Path(args.unlock),
        runner_contract=Path(args.runner_contract),
        replay_manifest=Path(args.replay_manifest),
        assignments=Path(args.assignments),
        membership=Path(args.membership),
        calendar=Path(args.calendar),
        daily_root=Path(args.daily_root),
        output=Path(args.output),
        ledger=Path(args.ledger),
    )
    unlock, prereg, contract = validate_control_plane(
        paths.unlock, paths.prereg, paths.runner_contract
    )
    run_formal(paths, unlock, prereg, contract)


if __name__ == "__main__":
    main()
