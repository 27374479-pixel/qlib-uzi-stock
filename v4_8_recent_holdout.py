"""V4.8 recent July/August 2026 replay using freshly backfilled Eastmoney 5m bars.

Purpose: extend the frozen long-only/cash V4.8 specification beyond the
persisted TraderHarness sample (which ends 2026-07-15) without changing any
selector, gate threshold, model hyperparameter, execution time or cost.

The workflow backfills Eastmoney 5-minute bars first. This script then:
- rebuilds X02 candidates from the same causal daily pipeline;
- uses Eastmoney 14:45 entry and next-session 10:00 exit prices;
- evaluates the seven frozen simple gates on 2026-08-01 onward;
- extends the pre-registered monthly expanding Logistic/Ridge gates, using only
  labels realized before each calendar month;
- reports BASE and CONSERVATIVE transaction-cost results.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43
import v4_8_long_only_gate_validation as v48

ROOT = Path(__file__).resolve().parent
EAST_DIR = ROOT / "data_lake" / "raw" / "eastmoney" / "equity_5min"
OUTPUT = ROOT / "output" / "v4_8_recent_holdout.json"
SUMMARY = ROOT / "output" / "v4_8_recent_holdout.csv"
RECENT_START = pd.Timestamp("2026-07-16")
HOLDOUT_START = pd.Timestamp("2026-08-01")


def _east_glob() -> str:
    files = list(EAST_DIR.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no Eastmoney minute files in {EAST_DIR}")
    return str((EAST_DIR / "*.parquet").resolve()).replace("'", "''")


def _recent_minute_extract(candidates: pd.DataFrame) -> pd.DataFrame:
    keys = candidates[["trade_date", "exit_date", "instrument"]].drop_duplicates().copy()
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.register("cand", keys)
    q = f"""
    SELECT
        CAST(c.trade_date AS DATE) AS trade_date,
        CAST(c.exit_date AS DATE) AS exit_date,
        c.instrument,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='09:35' THEN m.open END) AS day_open,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='14:30' THEN m.close END) AS px_1430,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='14:45' THEN m.close END) AS entry_1445,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='14:45' THEN m.volume END) AS entry_volume,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='14:45' THEN m.amount END) AS entry_amount,
        MAX(CASE WHEN CAST(m.datetime AS DATE)=CAST(c.exit_date AS DATE)
                  AND strftime(m.datetime, '%H:%M')='10:00' THEN m.close END) AS exit_1000
    FROM cand c
    JOIN read_parquet('{_east_glob()}', union_by_name=true) m
      ON m.instrument = c.instrument
     AND (
          CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
          OR CAST(m.datetime AS DATE)=CAST(c.exit_date AS DATE)
     )
    GROUP BY 1,2,3
    """
    out = con.execute(q).df()
    con.close()
    if not out.empty:
        out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.normalize()
        out["exit_date"] = pd.to_datetime(out["exit_date"]).dt.normalize()
    return out


def _east_market_features() -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    q = f"""
    WITH bars AS (
      SELECT
        CAST(datetime AS DATE) AS date,
        instrument,
        MAX(CASE WHEN strftime(datetime, '%H:%M')='11:30' THEN close END) AS px_1130,
        MAX(CASE WHEN strftime(datetime, '%H:%M')='14:30' THEN close END) AS px_1430,
        MAX(CASE WHEN strftime(datetime, '%H:%M')='14:40' THEN close END) AS px_1440,
        MAX(CASE WHEN strftime(datetime, '%H:%M')='15:00' THEN close END) AS px_1500,
        SUM(CASE WHEN strftime(datetime, '%H:%M')<='14:40'
                 THEN COALESCE(amount,0) ELSE 0 END) AS amount_1440
      FROM read_parquet('{_east_glob()}', union_by_name=true)
      WHERE UPPER(instrument) NOT LIKE 'SH688%'
      GROUP BY 1,2
    ),
    lagged AS (
      SELECT *, LAG(px_1500) OVER (PARTITION BY instrument ORDER BY date) AS prev_close
      FROM bars
    )
    SELECT
      date,
      COUNT(*) FILTER (WHERE px_1440 IS NOT NULL AND prev_close IS NOT NULL) AS n_1440,
      AVG(px_1440 / prev_close - 1.0)
        FILTER (WHERE px_1440 IS NOT NULL AND prev_close > 0) AS market_ret_1440,
      AVG(CASE WHEN px_1440 > prev_close THEN 1.0 ELSE 0.0 END)
        FILTER (WHERE px_1440 IS NOT NULL AND prev_close > 0) AS advance_ratio_1440,
      AVG(px_1440 / px_1130 - 1.0)
        FILTER (WHERE px_1440 IS NOT NULL AND px_1130 > 0) AS morning_to_afternoon,
      AVG(px_1440 / px_1430 - 1.0)
        FILTER (WHERE px_1440 IS NOT NULL AND px_1430 > 0) AS tail_strength,
      SUM(amount_1440) FILTER (WHERE px_1440 IS NOT NULL) AS total_amount_1440,
      AVG(px_1500 / prev_close - 1.0)
        FILTER (WHERE px_1500 IS NOT NULL AND prev_close > 0) AS close_ret,
      AVG(
        CASE
          WHEN px_1440 IS NULL OR prev_close IS NULL OR prev_close<=0 THEN NULL
          WHEN UPPER(instrument) LIKE 'SZ300%' AND px_1440/prev_close-1.0 >= 0.195 THEN 1.0
          WHEN UPPER(instrument) NOT LIKE 'SZ300%' AND px_1440/prev_close-1.0 >= 0.095 THEN 1.0
          ELSE 0.0
        END
      ) AS near_limit_up_ratio,
      AVG(
        CASE
          WHEN px_1440 IS NULL OR prev_close IS NULL OR prev_close<=0 THEN NULL
          WHEN UPPER(instrument) LIKE 'SZ300%' AND px_1440/prev_close-1.0 <= -0.195 THEN 1.0
          WHEN UPPER(instrument) NOT LIKE 'SZ300%' AND px_1440/prev_close-1.0 <= -0.095 THEN 1.0
          ELSE 0.0
        END
      ) AS near_limit_down_ratio
    FROM lagged
    GROUP BY 1
    ORDER BY 1
    """
    d = con.execute(q).df()
    con.close()
    d["trade_date"] = pd.to_datetime(d.pop("date")).dt.normalize()
    d = d.set_index("trade_date").sort_index()
    d["breadth5_1440"] = d["advance_ratio_1440"].rolling(5, min_periods=3).mean()
    prev_b5 = d["advance_ratio_1440"].rolling(5, min_periods=3).mean().shift(1)
    d["breadth5_delta"] = d["advance_ratio_1440"] - prev_b5
    amount_mean20 = d["total_amount_1440"].rolling(20, min_periods=10).mean().shift(1)
    d["amount_ratio20"] = d["total_amount_1440"] / amount_mean20.replace(0, np.nan)
    d["trend5_prev"] = d["close_ret"].rolling(5, min_periods=5).sum().shift(1)
    d["trend20_prev"] = d["close_ret"].rolling(20, min_periods=20).sum().shift(1)
    return d


def _slice_metrics(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    s = series[series.index >= HOLDOUT_START]
    l = ledger[pd.to_datetime(ledger["trade_date"]).dt.normalize() >= HOLDOUT_START].copy()
    if s.empty:
        return {"n_days": 0}
    m = v43._metrics(s, l)
    # Short holdout CAGR is mathematically valid but not decision-useful.
    m["holdout_total_return"] = m.get("total_return")
    m["holdout_start"] = str(s.index.min().date())
    m["holdout_end"] = str(s.index.max().date())
    return m


def _apply_gate(
    gate: pd.Series,
    series: pd.Series,
    ledger: pd.DataFrame,
) -> tuple[pd.Series, pd.DataFrame]:
    g = gate.reindex(series.index).fillna(False).astype(bool)
    live = series.where(g, 0.0)
    on_dates = set(pd.DatetimeIndex(g.index[g]))
    live_l = ledger[pd.to_datetime(ledger["trade_date"]).dt.normalize().isin(on_dates)].copy()
    return live, live_l


def run() -> dict[str, Any]:
    candidates, _ = v43._prepare_candidates()
    candidates["trade_date"] = pd.to_datetime(candidates["trade_date"]).dt.normalize()
    candidates["exit_date"] = pd.to_datetime(candidates["exit_date"]).dt.normalize()
    recent_candidates = candidates[candidates["trade_date"] >= RECENT_START].copy()
    if recent_candidates.empty:
        raise RuntimeError("daily candidate pipeline has no post-2026-07-15 candidates")

    minute = _recent_minute_extract(recent_candidates)
    feat = v43._add_intraday_features(recent_candidates, minute)
    eligible = feat[
        feat["base_executable"] & feat["limit_gap"].ge(v48.LIMIT_BUFFER)
    ].copy()
    eligible["score"] = eligible["clean_mom20_rank"].fillna(-np.inf)
    selected = v43._select_top(eligible, v48.TOP_N)

    recent_dates = sorted(recent_candidates["trade_date"].drop_duplicates())
    series_by_cost: dict[str, pd.Series] = {}
    ledger_by_cost: dict[str, pd.DataFrame] = {}
    for cost in ("BASE", "CONSERVATIVE"):
        s, l = v43._portfolio_series(selected, recent_dates, v48.EXIT, cost)
        series_by_cost[cost] = s
        ledger_by_cost[cost] = l

    simple = v48._simple_gate_table(candidates)
    report: dict[str, Any] = {
        "spec": {
            "frozen_from": "V4.8 long-only gate validation",
            "holdout_start": str(HOLDOUT_START.date()),
            "entry": "T 14:45 Eastmoney unadjusted 5m close",
            "exit": "T+1 10:00 Eastmoney unadjusted 5m close",
            "top_n": v48.TOP_N,
            "limit_buffer": v48.LIMIT_BUFFER,
            "simple_gates": list(v48.SIMPLE_GATES),
            "ml_models": ["LOGISTIC", "RIDGE"],
            "ml_feature_cutoff": "14:40",
            "no_parameter_changes": True,
        },
        "coverage": {
            "recent_candidate_rows": int(len(recent_candidates)),
            "recent_candidate_dates": int(recent_candidates["trade_date"].nunique()),
            "minute_matched_rows": int(len(minute)),
            "base_executable_rows": int(feat["base_executable"].sum()),
            "selected_rows": int(len(selected)),
            "selected_dates": int(selected["trade_date"].nunique()) if not selected.empty else 0,
            "first_selected_date": str(selected["trade_date"].min().date()) if not selected.empty else None,
            "last_selected_date": str(selected["trade_date"].max().date()) if not selected.empty else None,
        },
        "baseline": {},
        "simple_gates": {},
        "walk_forward_gates": {},
    }

    for cost in ("BASE", "CONSERVATIVE"):
        report["baseline"][cost] = _slice_metrics(series_by_cost[cost], ledger_by_cost[cost])

    for name in v48.SIMPLE_GATES:
        gate = simple[name]
        report["simple_gates"][name] = {"costs": {}}
        for cost in ("BASE", "CONSERVATIVE"):
            live, live_l = _apply_gate(gate, series_by_cost[cost], ledger_by_cost[cost])
            report["simple_gates"][name]["costs"][cost] = _slice_metrics(live, live_l)

    # Rebuild historical baseline/model features exactly as V4.8, then append
    # fresh post-07/15 observations. Monthly model refits remain causal.
    old_candidates, old_dates = v43._prepare_candidates()
    old_minute = v43._minute_extract(old_candidates)
    old_feat = v43._add_intraday_features(old_candidates, old_minute)
    if old_feat["base_executable"].any():
        first_exec = pd.Timestamp(old_feat.loc[old_feat["base_executable"], "trade_date"].min()).normalize()
        last_exec = pd.Timestamp(old_feat.loc[old_feat["base_executable"], "trade_date"].max()).normalize()
        old_dates = [d for d in old_dates if first_exec <= d <= last_exec]
    old_eligible = old_feat[
        old_feat["base_executable"] & old_feat["limit_gap"].ge(v48.LIMIT_BUFFER)
    ].copy()
    old_eligible["score"] = old_eligible["clean_mom20_rank"].fillna(-np.inf)
    old_selected = v43._select_top(old_eligible, v48.TOP_N)
    old_base, old_ledger = v43._portfolio_series(old_selected, old_dates, v48.EXIT, "BASE")
    old_active = pd.DatetimeIndex(pd.to_datetime(old_ledger["trade_date"]).dt.normalize().unique()).sort_values()

    new_ledger = ledger_by_cost["BASE"]
    new_active = pd.DatetimeIndex(pd.to_datetime(new_ledger["trade_date"]).dt.normalize().unique()).sort_values()
    combined_active = old_active.append(new_active[~new_active.isin(old_active)]).sort_values()
    target_return = old_base.reindex(combined_active)
    target_return.loc[new_active] = series_by_cost["BASE"].reindex(new_active)

    frozen = v48._frozen_features(candidates)
    old_market = v48._market_intraday_features()
    east_market = _east_market_features()
    last_old_market = old_market.index.max()
    market = pd.concat([old_market, east_market.loc[east_market.index > last_old_market]]).sort_index()
    market = market[~market.index.duplicated(keep="first")]

    model_frame = pd.DataFrame(index=combined_active)
    model_frame = model_frame.join(frozen, how="left").join(market, how="left")
    model_frame["frozen_weak_market"] = model_frame["frozen_weak_market"].astype("boolean").map({True: 1.0, False: 0.0})
    model_frame["base_net_return"] = target_return
    model_frame["target_up"] = (model_frame["base_net_return"] > 0).astype(float)

    report["ml_feature_coverage_holdout"] = {
        "holdout_active_days": int((model_frame.index >= HOLDOUT_START).sum()),
        "complete_holdout_feature_days": int(
            model_frame.loc[model_frame.index >= HOLDOUT_START, v48.MODEL_FEATURES]
            .notna().all(axis=1).sum()
        ),
        "market_cross_section_median_n": float(
            east_market.loc[east_market.index >= HOLDOUT_START, "n_1440"].median()
        ) if "n_1440" in east_market.columns else None,
    }

    # Score on the combined active-date frame, then apply only to the fresh
    # Eastmoney execution series. The monthly refit includes no current-month labels.
    for model_name in ("LOGISTIC", "RIDGE"):
        gate, score, refits = v48._walk_forward_gate(model_frame, model_name)
        report["walk_forward_gates"][model_name] = {
            "gate_on_holdout_days": int(gate.loc[gate.index >= HOLDOUT_START].fillna(False).sum()),
            "score_mean_holdout": float(score.loc[score.index >= HOLDOUT_START].dropna().mean())
                if score.loc[score.index >= HOLDOUT_START].notna().any() else None,
            "costs": {},
            "recent_refits": [r for r in refits if r["month"] >= "2026-08"],
        }
        for cost in ("BASE", "CONSERVATIVE"):
            live, live_l = _apply_gate(gate, series_by_cost[cost], ledger_by_cost[cost])
            report["walk_forward_gates"][model_name]["costs"][cost] = _slice_metrics(live, live_l)

    rows: list[dict[str, Any]] = []
    def add_row(name: str, costs: dict[str, Any]) -> None:
        b = costs.get("BASE", {})
        c = costs.get("CONSERVATIVE", {})
        rows.append({
            "strategy": name,
            "holdout_days": b.get("n_days"),
            "active_days": b.get("active_days"),
            "base_total_return": b.get("holdout_total_return"),
            "base_mean_active_day": b.get("mean_active_day"),
            "base_win_rate": b.get("active_win_rate"),
            "base_max_drawdown": b.get("max_drawdown"),
            "conservative_total_return": c.get("holdout_total_return"),
            "conservative_mean_active_day": c.get("mean_active_day"),
        })

    add_row("BASELINE_ALL", report["baseline"])
    for name in v48.SIMPLE_GATES:
        add_row(name, report["simple_gates"][name]["costs"])
    for name in ("LOGISTIC", "RIDGE"):
        add_row(name, report["walk_forward_gates"][name]["costs"])
    summary = pd.DataFrame(rows).sort_values("base_total_return", ascending=False, na_position="last")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary.to_csv(SUMMARY, index=False)
    print(summary.to_string(index=False))
    print(json.dumps(report["coverage"], ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
