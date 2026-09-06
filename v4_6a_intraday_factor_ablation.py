"""V4.6-A: causal intraday factor ablation for LIMIT_ADJUSTED_MOMENTUM.

Research question
-----------------
Can stock-level path information observed by T 14:45 improve the long-only
version of LIMIT_ADJUSTED_MOMENTUM, especially the weak 2021-2023 regime,
without sacrificing the profitable 2024-2026 regime?

This experiment is deliberately narrow:
* Daily candidate membership is still fixed after T-1 close.
* The market gate/base portfolio is frozen to the strongest simple V4.4/V4.5
  family: BREADTH5_AND_MONEY, Top3, entry T 14:45, exit T+1 10:00.
* Every new feature uses only bars with timestamp <= T 14:45.
* Single factors are ablated one at a time with a fixed 50/50 rank blend.
* A two-factor combination may be selected ONLY from 2021-2023 development
  results (and under both BASE and CONSERVATIVE costs). 2024-2026 is not used
  to choose the factors or weights.

The goal is not to optimize thresholds. It is to identify orthogonal information
that deserves independent follow-up validation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_6a_intraday_factor_ablation.json"
CSV_OUTPUT = ROOT / "output" / "v4_6a_intraday_factor_ablation.csv"

LIMIT_BUFFER = 0.005
TOP_N = 3
EXIT = "10:00"
COSTS = ("BASE", "CONSERVATIVE")
DEV_END = v43.OOS_START - pd.Timedelta(days=1)

# All directions are HIGHER = BETTER. DAY_RET and TAIL15 are included as
# reference controls because V4.3 already used them; the remaining factors are
# the genuinely richer V4.6-A path features.
FACTORS = {
    "DAY_RET": "intraday_ret",
    "TAIL15": "tail_ret",
    "CLOSE_VWAP": "close_vs_vwap",
    "RANGE_POS": "range_pos",
    "HIGH_HOLD": "from_high",
    "RET60": "ret60",
    "RET30": "ret30",
    "AFTERNOON_RET": "afternoon_ret",
}
NEW_FACTORS = (
    "CLOSE_VWAP",
    "RANGE_POS",
    "HIGH_HOLD",
    "RET60",
    "RET30",
    "AFTERNOON_RET",
)


def _market_mask(x: pd.DataFrame) -> pd.Series:
    # Frozen V4.5 base: both T-1 breadth5 and money_effect must be positive.
    return x["breadth5"].fillna(-1.0).gt(0) & x["money_effect"].fillna(-1.0).gt(0)


def _rich_trade_day_extract(candidates: pd.DataFrame) -> pd.DataFrame:
    """Aggregate only information known by 14:45 on the trade date T."""
    missing = [str(p) for p in v43.MINUTE_FILES if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing persisted minute files: {missing}")

    keys = candidates[["trade_date", "instrument"]].drop_duplicates().copy()
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.register("cand46", keys)
    files_sql = ",".join(
        "'" + str(p.resolve()).replace("'", "''") + "'" for p in v43.MINUTE_FILES
    )

    # 5-minute bars are end-labelled in this project. Therefore the 14:45 bar
    # close and every aggregate below through 14:45 are observable at decision
    # time; nothing after 14:45 is referenced.
    q = f"""
    WITH joined AS (
      SELECT
        CAST(c.trade_date AS DATE) AS trade_date,
        c.instrument,
        m.datetime,
        m.open,
        m.high,
        m.low,
        m.close,
        m.volume
      FROM cand46 c
      JOIN read_parquet([{files_sql}]) m
        ON m.instrument = c.instrument
       AND CAST(m.datetime AS DATE) = CAST(c.trade_date AS DATE)
      WHERE strftime(m.datetime, '%H:%M') >= '09:35'
        AND strftime(m.datetime, '%H:%M') <= '14:45'
    )
    SELECT
      trade_date,
      instrument,
      MAX(CASE WHEN strftime(datetime, '%H:%M')='13:05' THEN open END) AS px_1305_open,
      MAX(CASE WHEN strftime(datetime, '%H:%M')='13:45' THEN close END) AS px_1345,
      MAX(CASE WHEN strftime(datetime, '%H:%M')='14:15' THEN close END) AS px_1415,
      MAX(high) AS high_to_1445,
      MIN(low) AS low_to_1445,
      SUM(CASE WHEN volume > 0 THEN close * volume ELSE 0 END)
        / NULLIF(SUM(CASE WHEN volume > 0 THEN volume ELSE 0 END), 0) AS vwap_proxy,
      SUM(CASE WHEN strftime(datetime, '%H:%M') >= '13:45' AND volume > 0
               THEN volume ELSE 0 END)
        / NULLIF(SUM(CASE WHEN volume > 0 THEN volume ELSE 0 END), 0) AS late_volume_share,
      COUNT(*) AS bars_to_1445
    FROM joined
    GROUP BY 1,2
    """
    out = con.execute(q).df()
    con.close()
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    return out


def _add_rich_features(base_features: pd.DataFrame, rich: pd.DataFrame) -> pd.DataFrame:
    x = base_features.merge(rich, on=["trade_date", "instrument"], how="left", validate="one_to_one")

    x["close_vs_vwap"] = x["entry_1445"] / x["vwap_proxy"] - 1.0
    day_range = x["high_to_1445"] - x["low_to_1445"]
    x["range_pos"] = np.where(
        day_range > 0,
        (x["entry_1445"] - x["low_to_1445"]) / day_range,
        np.nan,
    )
    # Higher is better: 0 means sitting at the intraday high; -0.03 means 3%
    # below it at 14:45.
    x["from_high"] = x["entry_1445"] / x["high_to_1445"] - 1.0
    x["ret60"] = x["entry_1445"] / x["px_1345"] - 1.0
    x["ret30"] = x["entry_1445"] / x["px_1415"] - 1.0
    x["afternoon_ret"] = x["entry_1445"] / x["px_1305_open"] - 1.0

    # Guard against pathological bad bars without tuning any alpha threshold.
    x.loc[~np.isfinite(x["close_vs_vwap"]), "close_vs_vwap"] = np.nan
    x.loc[~np.isfinite(x["range_pos"]), "range_pos"] = np.nan
    x.loc[~np.isfinite(x["from_high"]), "from_high"] = np.nan
    x.loc[~np.isfinite(x["ret60"]), "ret60"] = np.nan
    x.loc[~np.isfinite(x["ret30"]), "ret30"] = np.nan
    x.loc[~np.isfinite(x["afternoon_ret"]), "afternoon_ret"] = np.nan
    return x


def _base_eligible(features: pd.DataFrame) -> pd.DataFrame:
    mask = (
        features["base_executable"]
        & features["limit_gap"].ge(LIMIT_BUFFER)
        & _market_mask(features)
    )
    return features.loc[mask].copy()


def _rank_frame(y: pd.DataFrame, factors: tuple[str, ...]) -> pd.DataFrame:
    """Fixed equal-weight rank blend: clean momentum + requested factors."""
    if y.empty:
        return y
    z = y.copy()
    needed = [FACTORS[f] for f in factors]
    if needed:
        z = z.dropna(subset=needed).copy()
    if z.empty:
        return z

    by_day = z.groupby("trade_date", sort=False)
    z["r_base"] = by_day["clean_mom20_rank"].rank(pct=True)
    rank_cols = ["r_base"]
    for factor in factors:
        col = FACTORS[factor]
        rcol = f"r_{factor.lower()}"
        z[rcol] = by_day[col].rank(pct=True)
        rank_cols.append(rcol)
    z["score"] = z[rank_cols].mean(axis=1)
    return z


def _period_metrics(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    all_s, all_l = v43._slice(series, ledger, None, None)
    dev_s, dev_l = v43._slice(series, ledger, None, DEV_END)
    oos_s, oos_l = v43._slice(series, ledger, v43.OOS_START, None)
    return {
        "all": v43._metrics(all_s, all_l),
        "development_2021_2023": v43._metrics(dev_s, dev_l),
        "oos_2024_2026": v43._metrics(oos_s, oos_l),
    }


def _evaluate(
    eligible: pd.DataFrame,
    all_dates: list[pd.Timestamp],
    factors: tuple[str, ...],
    cost: str,
    name: str,
) -> dict[str, Any]:
    ranked = _rank_frame(eligible, factors)
    selected = v43._select_top(ranked, TOP_N)
    series, ledger = v43._portfolio_series(selected, all_dates, EXIT, cost)
    return {
        "name": name,
        "factors": list(factors),
        "cost": cost,
        "top_n": TOP_N,
        "exit": EXIT,
        "limit_buffer": LIMIT_BUFFER,
        "eligible_rows": int(len(ranked)),
        "eligible_dates": int(ranked["trade_date"].nunique()) if not ranked.empty else 0,
        "metrics": _period_metrics(series, ledger),
    }


def _num(metric: dict[str, Any], key: str, fallback: float = -999.0) -> float:
    val = metric.get(key)
    return fallback if val is None else float(val)


def _select_dev_survivors(results: list[dict[str, Any]]) -> list[str]:
    """Choose at most two NEW factors using development data only.

    A factor must improve 2021-2023 CAGR by >=3 percentage points and not worsen
    development max drawdown under BOTH cost assumptions. Ranking is the mean
    CAGR improvement across BASE and CONSERVATIVE costs. No OOS field is read.
    """
    lookup = {(x["name"], x["cost"]): x for x in results}
    scores: list[tuple[float, str]] = []
    for factor in NEW_FACTORS:
        improvements = []
        ok = True
        for cost in COSTS:
            base = lookup[("BASELINE", cost)]["metrics"]["development_2021_2023"]
            item = lookup[(f"PLUS_{factor}", cost)]["metrics"]["development_2021_2023"]
            cagr_imp = _num(item, "cagr") - _num(base, "cagr")
            base_dd = _num(base, "max_drawdown", -1.0)
            item_dd = _num(item, "max_drawdown", -1.0)
            if cagr_imp < 0.03 or item_dd < base_dd:
                ok = False
                break
            improvements.append(cagr_imp)
        if ok:
            scores.append((float(np.mean(improvements)), factor))
    scores.sort(reverse=True)
    return [factor for _, factor in scores[:2]]


def _flat_rows(results: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for x in results:
        for period, m in x["metrics"].items():
            rows.append({
                "name": x["name"],
                "factors": "+".join(x["factors"]) if x["factors"] else "BASE",
                "cost": x["cost"],
                "period": period,
                "cagr": m.get("cagr"),
                "max_drawdown": m.get("max_drawdown"),
                "sharpe": m.get("sharpe"),
                "calmar": m.get("calmar"),
                "active_days": m.get("active_days"),
                "active_win_rate": m.get("active_win_rate"),
                "trade_rows": m.get("trade_rows"),
            })
    return pd.DataFrame(rows)


def run() -> dict[str, Any]:
    candidates, all_dates = v43._prepare_candidates()
    minute = v43._minute_extract(candidates)
    features = v43._add_intraday_features(candidates, minute)
    rich = _rich_trade_day_extract(candidates)
    features = _add_rich_features(features, rich)

    if features["base_executable"].any():
        first_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].min())
        last_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].max())
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]

    eligible = _base_eligible(features)
    results: list[dict[str, Any]] = []

    # Frozen baseline and single-factor ablations.
    for cost in COSTS:
        results.append(_evaluate(eligible, all_dates, (), cost, "BASELINE"))
        for factor in FACTORS:
            results.append(_evaluate(eligible, all_dates, (factor,), cost, f"PLUS_{factor}"))

    # Development-only selection. This function deliberately never reads OOS.
    dev_selected = _select_dev_survivors(results)
    if dev_selected:
        combo = tuple(dev_selected)
        combo_name = "DEV_SELECTED_" + "_".join(dev_selected)
        for cost in COSTS:
            results.append(_evaluate(eligible, all_dates, combo, cost, combo_name))

    base_lookup = {(x["name"], x["cost"]): x for x in results}
    base_base = base_lookup[("BASELINE", "BASE")]["metrics"]
    base_cons = base_lookup[("BASELINE", "CONSERVATIVE")]["metrics"]

    # Leaderboards are descriptive only. They do not alter the frozen combo.
    base_cost_results = [x for x in results if x["cost"] == "BASE"]
    dev_board = sorted(
        base_cost_results,
        key=lambda x: _num(x["metrics"]["development_2021_2023"], "cagr"),
        reverse=True,
    )
    oos_board = sorted(
        base_cost_results,
        key=lambda x: _num(x["metrics"]["oos_2024_2026"], "cagr"),
        reverse=True,
    )

    feature_coverage = {}
    for name, col in FACTORS.items():
        feature_coverage[name] = {
            "non_null_rows": int(eligible[col].notna().sum()),
            "coverage_fraction": float(eligible[col].notna().mean()) if len(eligible) else 0.0,
        }

    report = {
        "question": "Can causal T-day path-quality factors improve the V4.5 long-only base across regimes?",
        "preregistration": {
            "daily_signal": "LIMIT_ADJUSTED_MOMENTUM fixed at T-1 close",
            "market_gate": "T-1 breadth5 > 0 AND money_effect > 0",
            "entry": "T 14:45 5m bar close",
            "exit": "T+1 10:00 5m bar close",
            "portfolio": "Top3 equal-weight; require >=3 names",
            "limit_buffer": LIMIT_BUFFER,
            "single_factor_weight": "50% clean_mom20 within-day percentile rank + 50% factor percentile rank",
            "combo_weight": "equal weight of clean_mom20 rank and each development-selected factor rank",
            "combo_selection": "new factor must improve 2021-2023 CAGR by >=3pp and not worsen development MDD under BASE and CONSERVATIVE costs; choose best two by mean dev CAGR improvement",
            "oos_isolation": "combo selection function reads 2021-2023 development metrics only; 2024-2026 never selects factors or weights",
            "factor_directions": "all higher-is-better; no tuned thresholds",
        },
        "factor_definitions": {
            "DAY_RET": "T day 09:35 bar open -> 14:45 bar close return (V4.3 reference)",
            "TAIL15": "14:30 close -> 14:45 close return (V4.3 reference)",
            "CLOSE_VWAP": "14:45 close / volume-weighted mean 5m close through 14:45 - 1",
            "RANGE_POS": "14:45 close position inside T intraday high-low range through 14:45",
            "HIGH_HOLD": "14:45 close / intraday high through 14:45 - 1; closer to zero is better",
            "RET60": "13:45 close -> 14:45 close return",
            "RET30": "14:15 close -> 14:45 close return",
            "AFTERNOON_RET": "13:05 bar open -> 14:45 close return",
        },
        "coverage": {
            "candidate_rows": int(len(candidates)),
            "eligible_rows_after_execution_and_market_gate": int(len(eligible)),
            "eligible_dates": int(eligible["trade_date"].nunique()),
            "feature_coverage": feature_coverage,
        },
        "development_selected_factors": dev_selected,
        "baseline": {
            "BASE": base_base,
            "CONSERVATIVE": base_cons,
        },
        "results": results,
        "development_leaderboard_BASE": dev_board,
        "oos_leaderboard_BASE_descriptive_only": oos_board,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _flat_rows(results).to_csv(CSV_OUTPUT, index=False)

    print(json.dumps({
        "development_selected_factors": dev_selected,
        "baseline_dev": base_base["development_2021_2023"],
        "baseline_oos": base_base["oos_2024_2026"],
        "development_top5": [
            {
                "name": x["name"],
                "dev_cagr": x["metrics"]["development_2021_2023"].get("cagr"),
                "dev_mdd": x["metrics"]["development_2021_2023"].get("max_drawdown"),
                "oos_cagr_descriptive": x["metrics"]["oos_2024_2026"].get("cagr"),
            }
            for x in dev_board[:5]
        ],
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
