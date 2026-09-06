"""V4.10: test book-derived H03 climax avoidance as a veto on X02.

Frozen question:
Does the book-derived idea "do not chase broad theme climax / extreme consensus"
improve the already validated LIMIT_ADJUSTED_MOMENTUM (X02) portfolio without
changing X02's signal, rank, execution, or exit?

This is deliberately a veto test, not a new positive alpha.  H03 uses the
existing registered engineering proxy from daily_event_role_backtest:
  seal_n >= 4, broken_ratio <= 0.25, positive_ratio >= 0.62.
Those thresholds are NOT claimed to be literal book parameters and are not
optimized here.  We only compare the frozen proxy ON vs OFF.

Primary X02 portfolio is also frozen from V4.4:
- T-1 X02 signal;
- T-1 breadth5 > 0 and money_effect > 0;
- T 14:45 close entry;
- >=0.5% below upper limit;
- rank only clean_mom20_rank;
- Top3 equal weight;
- T+1 10:00 exit;
- BASE and CONSERVATIVE costs.

We additionally audit independence from X01 attention saturation.  X02 requires
hit_count20 <= 1, while the X01 saturation state is repeated limit attention;
therefore any overlap should be near zero by construction.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43
import v4_intraday_survivor_validation as base
import v4_survivor_wrapper as survivor

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_10_book_h03_climax_veto.json"
CSV_OUTPUT = ROOT / "output" / "v4_10_book_h03_climax_veto.csv"
LEDGER_OUTPUT = ROOT / "output" / "v4_10_book_h03_climax_veto_ledger.csv"

LIMIT_BUFFER = 0.005
TOP_N = 3
EXIT = "10:00"
COSTS = ("BASE", "CONSERVATIVE")


def _attach_h03(candidates: pd.DataFrame) -> pd.DataFrame:
    cfg = base.Config(start="2015-01-01", end="2026-09-03")
    frame = survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    cols = ["date", "instrument", "climax", "seal_n", "broken_ratio", "positive_ratio", "industry_code"]
    ctx = frame[cols].copy().rename(columns={
        "date": "signal_date",
        "climax": "h03_climax",
        "seal_n": "h03_seal_n",
        "broken_ratio": "h03_broken_ratio",
        "positive_ratio": "h03_positive_ratio",
        "industry_code": "signal_industry_code",
    })
    ctx = ctx.drop_duplicates(["signal_date", "instrument"], keep="last")
    x = candidates.merge(ctx, on=["signal_date", "instrument"], how="left", validate="many_to_one")
    x["h03_climax"] = x["h03_climax"].fillna(False).astype(bool)
    return x


def _eligible(features: pd.DataFrame) -> pd.DataFrame:
    mask = (
        features["base_executable"]
        & features["limit_gap"].ge(LIMIT_BUFFER)
        & features["breadth5"].fillna(-1).gt(0)
        & features["money_effect"].fillna(-1).gt(0)
    )
    y = features.loc[mask].copy()
    y["score"] = y["clean_mom20_rank"].fillna(-np.inf)
    return y


def _select(y: pd.DataFrame, veto: bool) -> pd.DataFrame:
    x = y.loc[~y["h03_climax"]].copy() if veto else y.copy()
    return v43._select_top(x, TOP_N)


def _period_metrics(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    all_s, all_l = v43._slice(series, ledger, None, None)
    dev_s, dev_l = v43._slice(series, ledger, None, v43.OOS_START - pd.Timedelta(days=1))
    oos_s, oos_l = v43._slice(series, ledger, v43.OOS_START, None)
    return {
        "all": v43._metrics(all_s, all_l),
        "development_2021_2023": v43._metrics(dev_s, dev_l),
        "oos_2024_2026": v43._metrics(oos_s, oos_l),
    }


def _delta_metrics(base_s: pd.Series, veto_s: pd.Series, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> dict[str, Any]:
    b, v = base_s.copy(), veto_s.copy()
    if start is not None:
        b, v = b[b.index >= start], v[v.index >= start]
    if end is not None:
        b, v = b[b.index <= end], v[v.index <= end]
    z = pd.concat([b.rename("baseline"), v.rename("veto")], axis=1).fillna(0.0)
    if z.empty:
        return {"days": 0}
    d = z["veto"] - z["baseline"]
    changed = d.ne(0)
    return {
        "days": int(len(z)),
        "changed_days": int(changed.sum()),
        "mean_daily_delta_all_days": float(d.mean()),
        "mean_daily_delta_changed_days": float(d.loc[changed].mean()) if changed.any() else 0.0,
        "veto_better_fraction_changed_days": float((d.loc[changed] > 0).mean()) if changed.any() else None,
        "pnl_corr": float(z.corr().iloc[0, 1]) if len(z) >= 3 else None,
    }


def _holding_diagnostics(baseline: pd.DataFrame, vetoed: pd.DataFrame) -> dict[str, Any]:
    bkeys = set(zip(pd.to_datetime(baseline["trade_date"]), baseline["instrument"].astype(str)))
    vkeys = set(zip(pd.to_datetime(vetoed["trade_date"]), vetoed["instrument"].astype(str)))
    union = bkeys | vkeys
    inter = bkeys & vkeys
    baseline_climax = baseline["h03_climax"].fillna(False).astype(bool) if not baseline.empty else pd.Series(dtype=bool)

    per_day: list[float] = []
    days = sorted(set(pd.to_datetime(baseline["trade_date"])) | set(pd.to_datetime(vetoed["trade_date"])))
    for d in days:
        a = set(baseline.loc[pd.to_datetime(baseline["trade_date"]).eq(d), "instrument"].astype(str))
        b = set(vetoed.loc[pd.to_datetime(vetoed["trade_date"]).eq(d), "instrument"].astype(str))
        if a or b:
            per_day.append(len(a & b) / len(a | b))
    return {
        "baseline_rows": int(len(baseline)),
        "veto_rows": int(len(vetoed)),
        "baseline_rows_directly_climax": int(baseline_climax.sum()) if len(baseline_climax) else 0,
        "baseline_climax_fraction": float(baseline_climax.mean()) if len(baseline_climax) else 0.0,
        "overall_holding_jaccard": float(len(inter) / len(union)) if union else None,
        "mean_daily_holding_jaccard": float(np.mean(per_day)) if per_day else None,
        "removed_baseline_positions": int(len(bkeys - vkeys)),
        "replacement_positions": int(len(vkeys - bkeys)),
    }


def run() -> dict[str, Any]:
    candidates, all_dates = v43._prepare_candidates()
    candidates = _attach_h03(candidates)
    minute = v43._minute_extract(candidates)
    features = v43._add_intraday_features(candidates, minute)
    if features["base_executable"].any():
        first_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].min())
        last_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].max())
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]

    eligible = _eligible(features)
    baseline_selected = _select(eligible, veto=False)
    veto_selected = _select(eligible, veto=True)
    holding_diag = _holding_diagnostics(baseline_selected, veto_selected)

    result_by_cost: dict[str, Any] = {}
    ledgers: list[pd.DataFrame] = []
    strict_flags = []
    risk_flags = []
    for cost in COSTS:
        base_s, base_l = v43._portfolio_series(baseline_selected, all_dates, EXIT, cost)
        veto_s, veto_l = v43._portfolio_series(veto_selected, all_dates, EXIT, cost)
        base_m = _period_metrics(base_s, base_l)
        veto_m = _period_metrics(veto_s, veto_l)
        delta = {
            "all": _delta_metrics(base_s, veto_s),
            "development_2021_2023": _delta_metrics(base_s, veto_s, end=v43.OOS_START - pd.Timedelta(days=1)),
            "oos_2024_2026": _delta_metrics(base_s, veto_s, start=v43.OOS_START),
        }
        result_by_cost[cost] = {"baseline": base_m, "h03_veto": veto_m, "delta": delta}

        strict = all(
            veto_m[p].get("cagr", -999) >= base_m[p].get("cagr", -999)
            for p in ("all", "development_2021_2023", "oos_2024_2026")
        ) and veto_m["all"].get("max_drawdown", -1) >= base_m["all"].get("max_drawdown", -1)
        risk_candidate = (
            veto_m["development_2021_2023"].get("cagr", -999) > base_m["development_2021_2023"].get("cagr", -999)
            and veto_m["all"].get("max_drawdown", -1) > base_m["all"].get("max_drawdown", -1)
            and veto_m["oos_2024_2026"].get("cagr", -999) > 0
        )
        strict_flags.append(strict)
        risk_flags.append(risk_candidate)

        for name, ledger in (("BASELINE", base_l), ("H03_VETO", veto_l)):
            z = ledger.copy()
            z["portfolio"] = name
            z["cost"] = cost
            ledgers.append(z)

    # X01's saturation control uses hit_count20>=4, while every X02 candidate
    # was selected with hit_count20<=1.  Audit rather than assume.
    sat_mask = pd.to_numeric(eligible["hit_count20"], errors="coerce").ge(4)
    climax_mask = eligible["h03_climax"].fillna(False).astype(bool)
    independence = {
        "eligible_x02_rows": int(len(eligible)),
        "h03_climax_rows": int(climax_mask.sum()),
        "h03_climax_fraction": float(climax_mask.mean()) if len(eligible) else None,
        "x01_saturated_rows_inside_x02": int(sat_mask.sum()),
        "x01_saturated_fraction_inside_x02": float(sat_mask.mean()) if len(eligible) else None,
        "h03_and_x01_saturated_overlap_rows": int((climax_mask & sat_mask).sum()),
        "interpretation": "H03 is a theme-level consensus state; X01 saturation is stock-level repeated limit attention. X02 already excludes repeated-hit saturation by construction.",
    }

    report = {
        "question": "Does frozen book-derived H03 climax avoidance improve the executable X02 portfolio as an independent veto overlay?",
        "source": {
            "H03": "48-trader-book registry: broad theme climax / consensus should not be chased",
            "proxy": "existing registered climax=(seal_n>=4 & broken_ratio<=0.25 & positive_ratio>=0.62); frozen, not optimized here",
            "X02": "LIMIT_ADJUSTED_MOMENTUM",
        },
        "frozen_strategy": {
            "market_gate": "T-1 breadth5>0 and money_effect>0",
            "rank": "clean_mom20_rank only",
            "top_n": TOP_N,
            "limit_buffer": LIMIT_BUFFER,
            "entry": "T 14:45 close",
            "exit": "T+1 10:00",
            "costs": list(COSTS),
        },
        "decision_rules": {
            "strict_dominance": "H03-veto CAGR >= baseline in all/dev/OOS and full MDD no worse, under both costs",
            "risk_overlay_candidate": "dev CAGR improves, full MDD improves, and OOS CAGR remains positive, under both costs",
            "no_parameter_search": True,
        },
        "coverage": {
            "candidate_rows": int(len(candidates)),
            "eligible_rows": int(len(eligible)),
            "eligible_dates": int(eligible["trade_date"].nunique()) if len(eligible) else 0,
        },
        "holding_diagnostics": holding_diag,
        "independence_from_x01": independence,
        "results": result_by_cost,
        "decision": {
            "strict_dominance_both_costs": bool(all(strict_flags)),
            "risk_overlay_candidate_both_costs": bool(all(risk_flags)),
        },
        "limitations": [
            "H03 climax remains an engineering proxy of book language, not a literal author formula.",
            "CSI industry is a theme proxy; true point-in-time concept/event data remains a future upgrade.",
            "2024-2026 has been seen by prior research and is a historical holdout, not pristine future validation.",
        ],
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    rows = []
    for cost, item in result_by_cost.items():
        for portfolio in ("baseline", "h03_veto"):
            for period, m in item[portfolio].items():
                rows.append({
                    "cost": cost, "portfolio": portfolio, "period": period,
                    "cagr": m.get("cagr"), "max_drawdown": m.get("max_drawdown"),
                    "sharpe": m.get("sharpe"), "calmar": m.get("calmar"),
                    "active_days": m.get("active_days"), "trade_rows": m.get("trade_rows"),
                })
    pd.DataFrame(rows).to_csv(CSV_OUTPUT, index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(LEDGER_OUTPUT, index=False)

    print(json.dumps({
        "coverage": report["coverage"],
        "holding_diagnostics": holding_diag,
        "independence_from_x01": independence,
        "decision": report["decision"],
        "summary": {
            cost: {
                "base_dev": result_by_cost[cost]["baseline"]["development_2021_2023"].get("cagr"),
                "veto_dev": result_by_cost[cost]["h03_veto"]["development_2021_2023"].get("cagr"),
                "base_oos": result_by_cost[cost]["baseline"]["oos_2024_2026"].get("cagr"),
                "veto_oos": result_by_cost[cost]["h03_veto"]["oos_2024_2026"].get("cagr"),
            } for cost in COSTS
        },
    }, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
