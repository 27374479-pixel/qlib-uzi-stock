"""V4.7 causal walk-forward orthogonal factor ensemble.

IMPORTANT: exploratory, not pristine OOS.  The architecture was designed after
reviewing 2021-2026 V4.3-V4.6 results.  However every historical decision is
causal: trade T uses only T-1 signal information and factor/strategy outcomes
that were realized before T 14:45.

Idea:
- keep LIMIT_ADJUSTED_MOMENTUM as the core cross-sectional factor;
- candidate secondary factors must be economically distinct and weakly related;
- residualize each secondary rank against the core each day;
- activate a secondary factor only when its prior 40 active-date IC history is
  positive and sufficiently consistent;
- greedily choose at most two currently weakly-correlated active factors;
- optionally require the base strategy's prior 40 active trades to have positive
  mean realized net return (a separate time-series regime gate).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43
import v4_6c_orthogonal_factor_screen as v46c

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_7_online_orthogonal_ensemble.json"
LEDGER = ROOT / "output" / "v4_7_online_orthogonal_ensemble_ledger.csv"

WINDOW = 40
MIN_HISTORY = 30
MIN_POSITIVE_IC_FRACTION = 0.55
MAX_CORE_CORR = 0.30
MAX_PAIR_CORR = 0.35
MAX_FACTORS = 2
TOP_N = 3
EXIT = "10:00"
COSTS = ("BASE", "CONSERVATIVE")

# TREND_EFF20 is excluded by the V4.6C correlation principle because its
# development mean absolute correlation with the core was ~0.52.  This is a
# correlation-only exclusion, not a return-based choice.
POOL = tuple(f for f in v46c.FACTORS if f != "TREND_EFF20")

VARIANTS = (
    "DYN_FACTOR_ONLY",
    "DYN_FACTOR_ACTIVE40",
)


def _prepare() -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    candidates, all_dates = v43._prepare_candidates()
    minute = v43._minute_extract(candidates)
    features = v43._add_intraday_features(candidates, minute)
    factors = v46c._daily_factor_frame()
    features = features.merge(
        factors,
        on=["signal_date", "instrument"],
        how="left",
        validate="many_to_one",
    )
    if features["base_executable"].any():
        first_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].min())
        last_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].max())
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]
    eligible = v46c._base_eligible(features)
    ranked = v46c._rank_columns(eligible)
    ortho = v46c._add_orthogonal_ranks(ranked)
    return ortho, all_dates


def _stock_net_returns(z: pd.DataFrame) -> pd.Series:
    return v43._net_return(z["entry_1445"], z["exit_1000"], z["trade_date"], "BASE")


def _daily_factor_ic(z: pd.DataFrame) -> pd.DataFrame:
    x = z.copy()
    x["realized_net"] = _stock_net_returns(x)
    dates = sorted(pd.to_datetime(x["trade_date"].drop_duplicates()))
    rows: list[dict[str, Any]] = []
    for d in dates:
        g = x[x["trade_date"] == d]
        row: dict[str, Any] = {"trade_date": pd.Timestamp(d)}
        for f in POOL:
            s = g[[f"o_{f}", "realized_net"]].dropna()
            row[f] = float(s[f"o_{f}"].corr(s["realized_net"], method="spearman")) if len(s) >= 20 else np.nan
        rows.append(row)
    return pd.DataFrame(rows).set_index("trade_date").sort_index()


def _trailing_ic_state(ic: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    # shift(1): trade date T sees factor outcomes only through the previous
    # eligible trade date; that previous trade exited by T 10:00 at latest.
    mean_ic = ic.rolling(WINDOW, min_periods=MIN_HISTORY).mean().shift(1)
    pos_frac = ic.gt(0).rolling(WINDOW, min_periods=MIN_HISTORY).mean().shift(1)
    return mean_ic, pos_frac


def _base_shadow(z: pd.DataFrame, all_dates: list[pd.Timestamp]) -> tuple[pd.Series, pd.DataFrame]:
    y = z.copy()
    y["score"] = y["r_base"]
    selected = v43._select_top(y, TOP_N)
    return v43._portfolio_series(selected, all_dates, EXIT, "BASE")


def _active40_gate(base_series: pd.Series) -> pd.Series:
    active = base_series[base_series.ne(0)].copy()
    score = active.rolling(WINDOW, min_periods=MIN_HISTORY).mean().shift(1)
    out = pd.Series(False, index=base_series.index, dtype=bool)
    out.loc[score.index] = score.gt(0).fillna(False)
    return out


def _current_corr(g: pd.DataFrame, a: str, b: str) -> float | None:
    s = g[[a, b]].dropna()
    if len(s) < 20:
        return None
    c = s[a].corr(s[b], method="pearson")  # ranks => Spearman
    return None if pd.isna(c) else float(c)


def _choose_factors(
    g: pd.DataFrame,
    date: pd.Timestamp,
    mean_ic: pd.DataFrame,
    pos_frac: pd.DataFrame,
) -> list[str]:
    if date not in mean_ic.index:
        return []
    candidates: list[tuple[float, str]] = []
    for f in POOL:
        mu = mean_ic.at[date, f] if f in mean_ic.columns else np.nan
        pf = pos_frac.at[date, f] if f in pos_frac.columns else np.nan
        if pd.isna(mu) or pd.isna(pf) or float(mu) <= 0 or float(pf) < MIN_POSITIVE_IC_FRACTION:
            continue
        c = _current_corr(g, "r_base", f"r_{f}")
        if c is None or abs(c) > MAX_CORE_CORR:
            continue
        candidates.append((float(mu), f))
    candidates.sort(reverse=True)

    chosen: list[str] = []
    for _, f in candidates:
        ok = True
        for prev in chosen:
            c = _current_corr(g, f"r_{prev}", f"r_{f}")
            if c is None or abs(c) > MAX_PAIR_CORR:
                ok = False
                break
        if ok:
            chosen.append(f)
        if len(chosen) >= MAX_FACTORS:
            break
    return chosen


def _select_walk_forward(
    z: pd.DataFrame,
    mean_ic: pd.DataFrame,
    pos_frac: pd.DataFrame,
    base_gate: pd.Series,
    variant: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    pieces: list[pd.DataFrame] = []
    factor_counts: Counter[str] = Counter()
    factor_count_by_date: dict[str, int] = {}
    skipped_no_factor = 0
    skipped_regime = 0

    for d, g0 in z.groupby("trade_date", sort=True):
        d = pd.Timestamp(d)
        if variant == "DYN_FACTOR_ACTIVE40" and not bool(base_gate.get(d, False)):
            skipped_regime += 1
            continue
        g = g0.copy()
        chosen = _choose_factors(g, d, mean_ic, pos_frac)
        if not chosen:
            skipped_no_factor += 1
            continue
        factor_count_by_date[str(d.date())] = len(chosen)
        factor_counts.update(chosen)
        score_cols = ["r_base"] + [f"o_{f}" for f in chosen]
        g = g.dropna(subset=score_cols).copy()
        if g.empty:
            continue
        g["score"] = g[score_cols].mean(axis=1)
        selected = v43._select_top(g, TOP_N)
        if selected.empty:
            continue
        selected["online_factors"] = "+".join(chosen)
        pieces.append(selected)

    out = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
    diag = {
        "factor_activation_counts": dict(factor_counts),
        "factor_count_by_date": factor_count_by_date,
        "skipped_no_factor_dates": int(skipped_no_factor),
        "skipped_regime_dates": int(skipped_regime),
        "selected_dates": int(out["trade_date"].nunique()) if not out.empty else 0,
    }
    return out, diag


def _metrics_by_period(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    all_s, all_l = v43._slice(series, ledger, None, None)
    p1_s, p1_l = v43._slice(series, ledger, None, pd.Timestamp("2023-12-31"))
    p2_s, p2_l = v43._slice(series, ledger, pd.Timestamp("2024-01-01"), None)
    return {
        "all": v43._metrics(all_s, all_l),
        "2021_2023": v43._metrics(p1_s, p1_l),
        "2024_2026": v43._metrics(p2_s, p2_l),
    }


def run() -> dict[str, Any]:
    z, all_dates = _prepare()
    ic = _daily_factor_ic(z)
    mean_ic, pos_frac = _trailing_ic_state(ic)
    base_shadow, base_ledger = _base_shadow(z, all_dates)
    base_gate = _active40_gate(base_shadow)

    results: list[dict[str, Any]] = []
    ledgers: list[pd.DataFrame] = []
    diagnostics: dict[str, Any] = {}

    # Baseline for context only.
    for cost in COSTS:
        y = z.copy()
        y["score"] = y["r_base"]
        selected = v43._select_top(y, TOP_N)
        series, ledger = v43._portfolio_series(selected, all_dates, EXIT, cost)
        results.append({"variant": "BASELINE", "cost": cost, "metrics": _metrics_by_period(series, ledger)})

    for variant in VARIANTS:
        selected, diag = _select_walk_forward(z, mean_ic, pos_frac, base_gate, variant)
        diagnostics[variant] = diag
        for cost in COSTS:
            series, ledger = v43._portfolio_series(selected, all_dates, EXIT, cost)
            results.append({"variant": variant, "cost": cost, "metrics": _metrics_by_period(series, ledger)})
            if cost == "BASE" and not ledger.empty:
                keep = ledger.copy()
                keep["variant"] = variant
                ledgers.append(keep)

    report = {
        "status": "EXPLORATORY_CAUSAL_WALK_FORWARD_NOT_PRISTINE_OOS",
        "reason": "V4.7 architecture was proposed after observing earlier 2021-2026 results; future unseen data is required for final validation.",
        "method": {
            "core": "LIMIT_ADJUSTED_MOMENTUM; breadth5>0 and money_effect>0; T14:45 entry; T+1 10:00 exit; Top3",
            "factor_pool": list(POOL),
            "factor_orthogonalization": "daily cross-sectional residual rank versus core",
            "ic_window_active_dates": WINDOW,
            "ic_min_history": MIN_HISTORY,
            "factor_active": f"prior rolling mean IC > 0 and positive-IC fraction >= {MIN_POSITIVE_IC_FRACTION}",
            "current_core_corr_abs_max": MAX_CORE_CORR,
            "current_pair_corr_abs_max": MAX_PAIR_CORR,
            "max_secondary_factors": MAX_FACTORS,
            "weights": "equal weight core + currently active orthogonal factors",
            "ACTIVE40": "base shadow strategy prior 40 active-trade mean net return > 0; shifted one trade date",
            "causality": "all realized-return states are shifted; previous trade exits by 10:00 before the new 14:45 decision",
        },
        "ic_summary": {
            f: {
                "mean": float(ic[f].mean()) if ic[f].notna().any() else None,
                "positive_fraction": float(ic[f].gt(0).mean()),
                "n": int(ic[f].notna().sum()),
            }
            for f in POOL
        },
        "base_active40_gate_days": int(base_gate.sum()),
        "diagnostics": diagnostics,
        "results": results,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(LEDGER, index=False)
    print(json.dumps({
        "status": report["status"],
        "base_active40_gate_days": report["base_active40_gate_days"],
        "diagnostics": diagnostics,
        "results": results,
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
