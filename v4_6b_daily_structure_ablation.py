"""V4.6-B: T-1 daily structure factor ablation.

V4.6-A showed that simply preferring stocks that look stronger into 14:45
(VWAP/high/range/late return) makes the long-only strategy worse. This stage
therefore moves upstream and asks whether the *structure already known at T-1
close* explains when LIMIT_ADJUSTED_MOMENTUM is investable.

Frozen base:
- LIMIT_ADJUSTED_MOMENTUM candidate fixed at T-1 close
- T-1 breadth5 > 0 and money_effect > 0
- executable at T 14:45 with 0.5% upper-limit buffer
- Top3 equal weight
- T+1 10:00 exit

No OOS result is used to select factors or weights. Single-factor variants use
one fixed equal-weight blend of clean momentum rank and the factor rank. A
maximum two-factor combination may be chosen from 2021-2023 development only,
and only if it improves CAGR by >=3pp and does not worsen max drawdown under
both BASE and CONSERVATIVE costs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_6b_daily_structure_ablation.json"
CSV_OUTPUT = ROOT / "output" / "v4_6b_daily_structure_ablation.csv"

LIMIT_BUFFER = 0.005
TOP_N = 3
EXIT = "10:00"
COSTS = ("BASE", "CONSERVATIVE")
DEV_END = v43.OOS_START - pd.Timedelta(days=1)

FACTORS = (
    "LOW_VOL10",
    "LOW_EXTENSION_MA20",
    "PULLBACK5",
    "TREND_EFF20",
    "AMOUNT_SWEET",
    "TURNOVER_SWEET",
)


def _market_mask(x: pd.DataFrame) -> pd.Series:
    return x["breadth5"].fillna(-1.0).gt(0) & x["money_effect"].fillna(-1.0).gt(0)


def _structural_frame() -> pd.DataFrame:
    """Build point-in-time structural features on the daily signal date."""
    cfg = v43.base.Config(start="2015-01-01", end="2026-09-03")
    frame = v43.survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.sort_values(["instrument", "date"]).reset_index(drop=True)

    by_stock = frame.groupby("instrument", sort=False)
    # Trend efficiency: displacement over total travelled log-return distance.
    # A smooth trend approaches 1; a noisy back-and-forth path approaches 0.
    log_ret = np.log(frame["close"] / frame["preclose"])
    frame["abs_log_ret"] = log_ret.abs()
    path20 = frame.groupby("instrument", sort=False)["abs_log_ret"].transform(
        lambda s: s.rolling(20, min_periods=15).sum()
    )
    lag20 = by_stock["close"].shift(20)
    displacement20 = np.log(frame["close"] / lag20).abs()
    frame["trend_eff20"] = displacement20 / path20.replace(0, np.nan)

    # Fixed, economically motivated direction scores. Higher is always better.
    frame["f_LOW_VOL10"] = -pd.to_numeric(frame["vol10"], errors="coerce")
    frame["f_LOW_EXTENSION_MA20"] = -pd.to_numeric(frame["price_to_ma20"], errors="coerce")
    frame["f_PULLBACK5"] = -pd.to_numeric(frame["ret5"], errors="coerce")
    frame["f_TREND_EFF20"] = pd.to_numeric(frame["trend_eff20"], errors="coerce")

    amount_accel = pd.to_numeric(frame["amount_accel"], errors="coerce")
    # Existing pre-registered research treats 1.2x-2.0x as moderate, healthy
    # acceleration. Score distance to this interval rather than optimizing a
    # single target after seeing returns.
    amount_dist = np.where(
        amount_accel < 1.2, 1.2 - amount_accel,
        np.where(amount_accel > 2.0, amount_accel - 2.0, 0.0),
    )
    frame["f_AMOUNT_SWEET"] = -pd.Series(amount_dist, index=frame.index)
    frame.loc[amount_accel.isna(), "f_AMOUNT_SWEET"] = np.nan

    turnover = pd.to_numeric(frame["turnover_rate_pct"], errors="coerce")
    # Existing pre-registered research treats 3%-15% as the normal active
    # turnover zone. Again use distance to the interval, not a tuned center.
    turn_dist = np.where(
        turnover < 3.0, 3.0 - turnover,
        np.where(turnover > 15.0, turnover - 15.0, 0.0),
    )
    frame["f_TURNOVER_SWEET"] = -pd.Series(turn_dist, index=frame.index)
    frame.loc[turnover.isna(), "f_TURNOVER_SWEET"] = np.nan

    cols = ["date", "instrument"] + [f"f_{name}" for name in FACTORS]
    out = frame[cols].rename(columns={"date": "signal_date"}).copy()
    return out.drop_duplicates(["signal_date", "instrument"], keep="last")


def _base_eligible(features: pd.DataFrame) -> pd.DataFrame:
    mask = (
        features["base_executable"]
        & features["limit_gap"].ge(LIMIT_BUFFER)
        & _market_mask(features)
    )
    return features.loc[mask].copy()


def _rank_frame(y: pd.DataFrame, factors: tuple[str, ...]) -> pd.DataFrame:
    if y.empty:
        return y
    z = y.copy()
    needed = [f"f_{name}" for name in factors]
    if needed:
        z = z.dropna(subset=needed).copy()
    if z.empty:
        return z

    by_day = z.groupby("trade_date", sort=False)
    z["r_base"] = by_day["clean_mom20_rank"].rank(pct=True)
    rank_cols = ["r_base"]
    for name in factors:
        rcol = f"r_{name.lower()}"
        z[rcol] = by_day[f"f_{name}"].rank(pct=True)
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
        "eligible_rows": int(len(ranked)),
        "eligible_dates": int(ranked["trade_date"].nunique()) if not ranked.empty else 0,
        "metrics": _period_metrics(series, ledger),
    }


def _num(metric: dict[str, Any], key: str, fallback: float = -999.0) -> float:
    value = metric.get(key)
    return fallback if value is None else float(value)


def _select_dev_survivors(results: list[dict[str, Any]]) -> list[str]:
    lookup = {(x["name"], x["cost"]): x for x in results}
    scored: list[tuple[float, str]] = []
    for factor in FACTORS:
        improvements = []
        ok = True
        for cost in COSTS:
            base = lookup[("BASELINE", cost)]["metrics"]["development_2021_2023"]
            item = lookup[(f"PLUS_{factor}", cost)]["metrics"]["development_2021_2023"]
            imp = _num(item, "cagr") - _num(base, "cagr")
            if imp < 0.03 or _num(item, "max_drawdown", -1.0) < _num(base, "max_drawdown", -1.0):
                ok = False
                break
            improvements.append(imp)
        if ok:
            scored.append((float(np.mean(improvements)), factor))
    scored.sort(reverse=True)
    return [name for _, name in scored[:2]]


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
    structural = _structural_frame()
    features = features.merge(
        structural,
        on=["signal_date", "instrument"],
        how="left",
        validate="many_to_one",
    )

    if features["base_executable"].any():
        first_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].min())
        last_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].max())
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]

    eligible = _base_eligible(features)
    results: list[dict[str, Any]] = []
    for cost in COSTS:
        results.append(_evaluate(eligible, all_dates, (), cost, "BASELINE"))
        for factor in FACTORS:
            results.append(_evaluate(eligible, all_dates, (factor,), cost, f"PLUS_{factor}"))

    dev_selected = _select_dev_survivors(results)
    if dev_selected:
        combo = tuple(dev_selected)
        name = "DEV_SELECTED_" + "_".join(dev_selected)
        for cost in COSTS:
            results.append(_evaluate(eligible, all_dates, combo, cost, name))

    base_results = [x for x in results if x["cost"] == "BASE"]
    dev_board = sorted(
        base_results,
        key=lambda x: _num(x["metrics"]["development_2021_2023"], "cagr"),
        reverse=True,
    )
    oos_board = sorted(
        base_results,
        key=lambda x: _num(x["metrics"]["oos_2024_2026"], "cagr"),
        reverse=True,
    )

    coverage = {}
    for factor in FACTORS:
        col = f"f_{factor}"
        coverage[factor] = {
            "non_null_rows": int(eligible[col].notna().sum()),
            "coverage_fraction": float(eligible[col].notna().mean()) if len(eligible) else 0.0,
        }

    report = {
        "question": "Can T-1 stock structure repair the long-only regime split that intraday chasing could not?",
        "preregistration": {
            "base": "LIMIT_ADJUSTED_MOMENTUM + breadth5>0 + money_effect>0 + Top3 + T14:45/T+1 10:00",
            "single_factor_blend": "50% clean momentum within-day rank + 50% structural factor rank",
            "combo_selection": "2021-2023 only; >=3pp CAGR improvement and no worse MDD under both costs; max two factors",
            "oos_isolation": "2024-2026 is descriptive validation only and never used for selection",
            "factor_directions_fixed_before_run": True,
        },
        "factor_definitions": {
            "LOW_VOL10": "prefer lower 10-day daily-return volatility",
            "LOW_EXTENSION_MA20": "prefer less price extension above/below MA20 within an already-strong core universe",
            "PULLBACK5": "prefer lower recent 5-day return within the strong 20-day core; anti-chase hypothesis",
            "TREND_EFF20": "prefer larger 20-day net log displacement / total absolute log-return path",
            "AMOUNT_SWEET": "prefer amount_accel inside existing pre-registered 1.2x-2.0x moderate acceleration interval",
            "TURNOVER_SWEET": "prefer turnover inside existing pre-registered 3%-15% active interval",
        },
        "coverage": {
            "candidate_rows": int(len(candidates)),
            "eligible_rows": int(len(eligible)),
            "eligible_dates": int(eligible["trade_date"].nunique()),
            "factor_coverage": coverage,
        },
        "development_selected_factors": dev_selected,
        "results": results,
        "development_leaderboard_BASE": dev_board,
        "oos_leaderboard_BASE_descriptive_only": oos_board,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _flat_rows(results).to_csv(CSV_OUTPUT, index=False)
    print(json.dumps({
        "development_selected_factors": dev_selected,
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
