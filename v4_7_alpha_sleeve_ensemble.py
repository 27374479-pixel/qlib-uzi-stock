"""V4.7: weakly-correlated alpha sleeve ensemble.

Instead of blending many descriptors into one stock score, this stage treats
mechanistically distinct hypotheses as separate sleeves. Each sleeve selects
its own Top3, trades with the same causal execution convention, and contributes
its own P&L stream. Development selection is 2021-2023 only; 2024-2026 remains
untouched OOS.

Frozen execution:
- signal fixed at T-1 close;
- buy T 14:45 5m bar close, only if executable and >=0.5% below upper limit;
- Top3 equal-weight within each sleeve;
- sell T+1 10:00 5m bar close;
- BASE and CONSERVATIVE costs from V4.3.

Sleeves:
- CORE_X02: limit-adjusted momentum, with breadth5>0 & money_effect>0 gate;
- REVERSAL_X06: weak-broad-day, >2% decliner, top-20% turnover; rank turnover;
- OVERNIGHT_X07: mid raw-momentum, top-20% overnight momentum; rank overnight momentum;
- OVERNIGHT_VS_INTRADAY_X07B: overnight-dominated vs intraday-dominated strength;
  rank overnight-rank minus intraday-rank.

New sleeves may join the ensemble only if, on 2021-2023 development:
- BASE CAGR > 0;
- CONSERVATIVE CAGR >= 0;
- max drawdown > -35% under both costs;
- absolute zero-filled daily P&L correlation with CORE <= 0.25;
- active-day overlap with CORE <= 60%.
At most two new sleeves are selected, greedily by BASE development Calmar, with
pairwise absolute P&L correlation <= 0.35. Ensemble capital is fixed equal split
across CORE and selected sleeves; idle sleeve capital stays cash.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43
from external_challenger_daily_screen import challenger_masks

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_7_alpha_sleeve_ensemble.json"
CSV_OUTPUT = ROOT / "output" / "v4_7_alpha_sleeve_ensemble.csv"

LIMIT_BUFFER = 0.005
TOP_N = 3
EXIT = "10:00"
COSTS = ("BASE", "CONSERVATIVE")
DEV_END = v43.OOS_START - pd.Timedelta(days=1)

SLEEVES = (
    "CORE_X02",
    "REVERSAL_X06",
    "OVERNIGHT_X07",
    "OVERNIGHT_VS_INTRADAY_X07B",
)


def _next_map(frame: pd.DataFrame) -> dict[pd.Timestamp, pd.Timestamp]:
    dates = sorted(pd.to_datetime(frame["date"]).dt.normalize().drop_duplicates())
    return {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}


def _prepare_candidates() -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    cfg = v43.base.Config(start="2015-01-01", end="2026-09-03")
    frame = v43.survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    masks = challenger_masks(frame)
    nxt = _next_map(frame)

    specs = {
        "CORE_X02": masks["X02_limit_adjusted_momentum"]["selected"].fillna(False),
        "REVERSAL_X06": masks["X06_t1_high_turnover_decline_reversal"]["selected"].fillna(False),
        "OVERNIGHT_X07": masks["X07_overnight_information"]["selected"].fillna(False),
        "OVERNIGHT_VS_INTRADAY_X07B": masks["X07b_overnight_vs_intraday_momentum"]["selected"].fillna(False),
    }

    signal_cols = [
        "date", "instrument", "close", "breadth", "breadth5", "money_effect",
        "weak_market", "raw_mom20_rank", "clean_mom20_rank", "hit_count20",
        "turnover_market_rank", "overnight_mom20_rank", "intraday_mom20_rank",
        "ret1",
    ]
    parts: list[pd.DataFrame] = []
    for sleeve, mask in specs.items():
        x = frame.loc[mask, signal_cols].copy()
        x = x.rename(columns={
            "date": "signal_date",
            "close": "signal_close",
            "weak_market": "signal_weak_market",
        })
        x["trade_date"] = x["signal_date"].map(nxt)
        x["exit_date"] = x["trade_date"].map(nxt)
        x["sleeve"] = sleeve
        parts.append(x)

    x = pd.concat(parts, ignore_index=True)
    x = x.dropna(subset=["trade_date", "exit_date"]).copy()
    x["trade_date"] = pd.to_datetime(x["trade_date"]).dt.normalize()
    x["exit_date"] = pd.to_datetime(x["exit_date"]).dt.normalize()
    x = x[x["trade_date"] >= v43.SAMPLE_START].copy()
    x = x[~x["instrument"].astype(str).str.upper().str.startswith("SH688")].copy()

    ref_cols = ["date", "instrument", "preclose", "upper_limit", "lower_limit"]
    for optional in ("trade_status", "is_st"):
        if optional in frame.columns:
            ref_cols.append(optional)
    ref = frame[ref_cols].rename(columns={"date": "trade_date"}).copy()
    x = x.merge(ref, on=["trade_date", "instrument"], how="left", validate="many_to_one")
    if "trade_status" in x.columns:
        x = x[x["trade_status"].fillna(0).eq(1)]
    if "is_st" in x.columns:
        x = x[x["is_st"].fillna(1).eq(0)]

    x = x.drop_duplicates(["sleeve", "trade_date", "instrument"]).reset_index(drop=True)
    all_dates = [
        d for d in sorted(frame["date"].drop_duplicates())
        if d >= v43.SAMPLE_START and d <= x["trade_date"].max()
    ]
    return x, all_dates


def _rank_sleeve(features: pd.DataFrame, sleeve: str) -> pd.DataFrame:
    y = features[
        features["sleeve"].eq(sleeve)
        & features["base_executable"]
        & features["limit_gap"].ge(LIMIT_BUFFER)
    ].copy()

    if sleeve == "CORE_X02":
        y = y[y["breadth5"].fillna(-1).gt(0) & y["money_effect"].fillna(-1).gt(0)].copy()
        y["score"] = pd.to_numeric(y["clean_mom20_rank"], errors="coerce")
    elif sleeve == "REVERSAL_X06":
        y["score"] = pd.to_numeric(y["turnover_market_rank"], errors="coerce")
    elif sleeve == "OVERNIGHT_X07":
        y["score"] = pd.to_numeric(y["overnight_mom20_rank"], errors="coerce")
    elif sleeve == "OVERNIGHT_VS_INTRADAY_X07B":
        y["score"] = (
            pd.to_numeric(y["overnight_mom20_rank"], errors="coerce")
            - pd.to_numeric(y["intraday_mom20_rank"], errors="coerce")
        )
    else:
        raise ValueError(sleeve)
    y = y.dropna(subset=["score"])
    return v43._select_top(y, TOP_N)


def _period_metrics(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    all_s, all_l = v43._slice(series, ledger, None, None)
    dev_s, dev_l = v43._slice(series, ledger, None, DEV_END)
    oos_s, oos_l = v43._slice(series, ledger, v43.OOS_START, None)
    return {
        "all": v43._metrics(all_s, all_l),
        "development_2021_2023": v43._metrics(dev_s, dev_l),
        "oos_2024_2026": v43._metrics(oos_s, oos_l),
    }


def _corr(a: pd.Series, b: pd.Series, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> float | None:
    x = pd.concat([a.rename("a"), b.rename("b")], axis=1).fillna(0.0)
    if start is not None:
        x = x[x.index >= start]
    if end is not None:
        x = x[x.index <= end]
    if len(x) < 20 or x["a"].std() == 0 or x["b"].std() == 0:
        return None
    return float(x["a"].corr(x["b"]))


def _active_overlap(a: pd.Series, b: pd.Series, end: pd.Timestamp) -> float:
    aa = a.loc[a.index <= end].ne(0)
    bb = b.loc[b.index <= end].ne(0)
    union = int((aa | bb).sum())
    return float((aa & bb).sum() / union) if union else 0.0


def _holding_overlap(a: pd.DataFrame, b: pd.DataFrame, end: pd.Timestamp) -> float | None:
    aa = a[a["trade_date"] <= end].groupby("trade_date")["instrument"].apply(set)
    bb = b[b["trade_date"] <= end].groupby("trade_date")["instrument"].apply(set)
    dates = aa.index.intersection(bb.index)
    if not len(dates):
        return None
    vals = [len(aa.loc[d] & bb.loc[d]) / float(TOP_N) for d in dates]
    return float(np.mean(vals)) if vals else None


def _select_new_sleeves(series_by: dict[tuple[str, str], pd.Series], ledgers: dict[tuple[str, str], pd.DataFrame], metrics: dict[tuple[str, str], dict[str, Any]]) -> list[str]:
    candidates: list[tuple[float, str]] = []
    core_base = series_by[("CORE_X02", "BASE")]
    for sleeve in SLEEVES[1:]:
        mb = metrics[(sleeve, "BASE")]["development_2021_2023"]
        mc = metrics[(sleeve, "CONSERVATIVE")]["development_2021_2023"]
        cagr_b = mb.get("cagr")
        cagr_c = mc.get("cagr")
        mdd_b = mb.get("max_drawdown")
        mdd_c = mc.get("max_drawdown")
        corr = _corr(core_base, series_by[(sleeve, "BASE")], end=DEV_END)
        overlap = _active_overlap(core_base, series_by[(sleeve, "BASE")], DEV_END)
        ok = (
            cagr_b is not None and cagr_b > 0
            and cagr_c is not None and cagr_c >= 0
            and mdd_b is not None and mdd_b > -0.35
            and mdd_c is not None and mdd_c > -0.35
            and corr is not None and abs(corr) <= 0.25
            and overlap <= 0.60
        )
        if ok:
            calmar = mb.get("calmar")
            score = float(calmar) if calmar is not None else float(cagr_b)
            candidates.append((score, sleeve))

    candidates.sort(reverse=True)
    selected: list[str] = []
    for _, sleeve in candidates:
        if len(selected) >= 2:
            break
        pair_ok = True
        for prior in selected:
            c = _corr(series_by[(prior, "BASE")], series_by[(sleeve, "BASE")], end=DEV_END)
            if c is None or abs(c) > 0.35:
                pair_ok = False
                break
        if pair_ok:
            selected.append(sleeve)
    return selected


def _ensemble_series(series_by: dict[tuple[str, str], pd.Series], sleeves: list[str], cost: str) -> pd.Series:
    members = ["CORE_X02"] + sleeves
    parts = [series_by[(s, cost)] for s in members]
    x = pd.concat(parts, axis=1).fillna(0.0)
    return x.mean(axis=1)


def _ensemble_ledger(ledgers: dict[tuple[str, str], pd.DataFrame], sleeves: list[str], cost: str) -> pd.DataFrame:
    members = ["CORE_X02"] + sleeves
    parts = []
    for s in members:
        x = ledgers[(s, cost)].copy()
        x["ensemble_sleeve"] = s
        parts.append(x)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def run() -> dict[str, Any]:
    candidates, all_dates = _prepare_candidates()
    minute_keys = candidates[["trade_date", "exit_date", "instrument"]].drop_duplicates().copy()
    minute = v43._minute_extract(minute_keys)
    features = v43._add_intraday_features(candidates, minute)

    if features["base_executable"].any():
        first_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].min())
        last_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].max())
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]

    series_by: dict[tuple[str, str], pd.Series] = {}
    ledgers: dict[tuple[str, str], pd.DataFrame] = {}
    metrics: dict[tuple[str, str], dict[str, Any]] = {}
    results: list[dict[str, Any]] = []

    selected_rows: dict[str, pd.DataFrame] = {s: _rank_sleeve(features, s) for s in SLEEVES}
    for sleeve in SLEEVES:
        for cost in COSTS:
            series, ledger = v43._portfolio_series(selected_rows[sleeve], all_dates, EXIT, cost)
            series_by[(sleeve, cost)] = series
            ledgers[(sleeve, cost)] = ledger
            m = _period_metrics(series, ledger)
            metrics[(sleeve, cost)] = m
            results.append({"name": sleeve, "cost": cost, "metrics": m})

    corr_dev: dict[str, Any] = {}
    for i, a in enumerate(SLEEVES):
        for b in SLEEVES[i + 1:]:
            corr_dev[f"{a}|{b}"] = {
                "pnl_corr": _corr(series_by[(a, "BASE")], series_by[(b, "BASE")], end=DEV_END),
                "active_day_jaccard": _active_overlap(series_by[(a, "BASE")], series_by[(b, "BASE")], DEV_END),
                "holding_overlap_when_both_active": _holding_overlap(ledgers[(a, "BASE")], ledgers[(b, "BASE")], DEV_END),
            }

    selected_new = _select_new_sleeves(series_by, ledgers, metrics)
    ensemble_out: dict[str, Any] = {}
    for cost in COSTS:
        s = _ensemble_series(series_by, selected_new, cost)
        l = _ensemble_ledger(ledgers, selected_new, cost)
        ensemble_out[cost] = _period_metrics(s, l)

    # A descriptive equal-weight all-sleeve reference; never used for selection.
    all_sleeves_out: dict[str, Any] = {}
    for cost in COSTS:
        s = pd.concat([series_by[(x, cost)] for x in SLEEVES], axis=1).fillna(0.0).mean(axis=1)
        l = pd.concat([ledgers[(x, cost)].assign(ensemble_sleeve=x) for x in SLEEVES], ignore_index=True)
        all_sleeves_out[cost] = _period_metrics(s, l)

    report = {
        "question": "Do mechanistically distinct alpha sleeves diversify the overnight strategy better than factor-score blending?",
        "preregistration": {
            "development": "2021-2023 only",
            "oos": "2024-2026 untouched for sleeve selection",
            "execution": "T-1 signal, T 14:45 close entry, >=0.5% below upper limit, Top3, T+1 10:00 exit",
            "new_sleeve_gate": "BASE CAGR>0; CONS CAGR>=0; both MDD>-35%; abs PnL corr to CORE<=0.25; active-day Jaccard<=0.60",
            "pair_gate": "abs development PnL corr<=0.35",
            "allocation": "fixed equal capital across CORE and selected new sleeves; idle sleeve capital remains cash",
            "max_new_sleeves": 2,
        },
        "sleeve_definitions": {
            "CORE_X02": "limit-adjusted momentum + breadth5>0 + money_effect>0; rank clean_mom20",
            "REVERSAL_X06": "weak broad day + stock down >2% + top20% turnover; rank turnover",
            "OVERNIGHT_X07": "mid raw momentum + top20% overnight momentum; rank overnight momentum",
            "OVERNIGHT_VS_INTRADAY_X07B": "top20% overnight momentum + intraday rank<=60%; rank overnight minus intraday rank",
        },
        "coverage": {
            "candidate_rows": int(len(candidates)),
            "feature_rows": int(len(features)),
            "selected_rows": {s: int(len(selected_rows[s])) for s in SLEEVES},
            "active_dates": {s: int(selected_rows[s]["trade_date"].nunique()) if len(selected_rows[s]) else 0 for s in SLEEVES},
        },
        "development_pair_diagnostics": corr_dev,
        "development_selected_new_sleeves": selected_new,
        "individual_results": results,
        "selected_ensemble": ensemble_out,
        "all_four_sleeves_descriptive_only": all_sleeves_out,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    rows = []
    for x in results:
        for period, m in x["metrics"].items():
            rows.append({
                "name": x["name"], "cost": x["cost"], "period": period,
                "cagr": m.get("cagr"), "max_drawdown": m.get("max_drawdown"),
                "sharpe": m.get("sharpe"), "calmar": m.get("calmar"),
                "active_days": m.get("active_days"), "active_win_rate": m.get("active_win_rate"),
            })
    for cost, periods in ensemble_out.items():
        for period, m in periods.items():
            rows.append({
                "name": "SELECTED_ENSEMBLE", "cost": cost, "period": period,
                "cagr": m.get("cagr"), "max_drawdown": m.get("max_drawdown"),
                "sharpe": m.get("sharpe"), "calmar": m.get("calmar"),
                "active_days": m.get("active_days"), "active_win_rate": m.get("active_win_rate"),
            })
    pd.DataFrame(rows).to_csv(CSV_OUTPUT, index=False)
    print(json.dumps({
        "selected_new_sleeves": selected_new,
        "pair_diagnostics": corr_dev,
        "selected_ensemble": ensemble_out,
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
