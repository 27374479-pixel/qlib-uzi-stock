"""V4.6-C: orthogonal/weak-correlation factor screen for the long-only overnight strategy.

Principle: a second factor is useful only if it adds information that is not
already encoded by LIMIT_ADJUSTED_MOMENTUM.  We therefore impose correlation
constraints BEFORE looking at portfolio improvement.

Frozen base:
- LIMIT_ADJUSTED_MOMENTUM fixed at T-1 close
- T-1 breadth5 > 0 and money_effect > 0
- T 14:45 executable entry with 0.5% upper-limit buffer
- Top3 equal weight
- T+1 10:00 exit

Development selection uses 2021-2023 only.  2024-2026 is untouched OOS.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_6c_orthogonal_factor_screen.json"
RESULT_CSV = ROOT / "output" / "v4_6c_orthogonal_factor_screen.csv"
CORR_CSV = ROOT / "output" / "v4_6c_factor_correlations.csv"

LIMIT_BUFFER = 0.005
TOP_N = 3
EXIT = "10:00"
COSTS = ("BASE", "CONSERVATIVE")
DEV_END = v43.OOS_START - pd.Timedelta(days=1)
MIN_CORR_N = 20
MAX_CORE_MEAN_ABS_CORR = 0.30
MAX_CORE_P90_ABS_CORR = 0.55
MAX_PAIR_MEAN_ABS_CORR = 0.35
MIN_DEV_CAGR_IMPROVEMENT = 0.03

FACTORS = (
    # Prior V4.6B representatives.
    "LOW_VOL10",
    "PULLBACK5",
    "TREND_EFF20",
    "TURNOVER_SWEET",
    # New domains deliberately chosen to be economically distinct.
    "LOW_ABS_GAP1",
    "HIGH_CLOSE_LOC1",
    "LOW_UPPER_SHADOW1",
    "LOW_AMPLITUDE1",
    "LOW_TURNOVER_ACCEL5",
    "HIGH_LIQUIDITY",
    "SMALLER_FLOAT_CAP",
    "LOW_GAP_VOL10",
)


def _market_mask(x: pd.DataFrame) -> pd.Series:
    return x["breadth5"].fillna(-1.0).gt(0) & x["money_effect"].fillna(-1.0).gt(0)


def _daily_factor_frame() -> pd.DataFrame:
    cfg = v43.base.Config(start="2015-01-01", end="2026-09-03")
    frame = v43.survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.sort_values(["instrument", "date"]).reset_index(drop=True)
    by_stock = frame.groupby("instrument", sort=False)

    close = pd.to_numeric(frame["close"], errors="coerce")
    preclose = pd.to_numeric(frame["preclose"], errors="coerce")
    open_px = pd.to_numeric(frame["open"], errors="coerce")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    amount = pd.to_numeric(frame["amount"], errors="coerce")
    turnover = pd.to_numeric(frame["turnover_rate_pct"], errors="coerce")

    ret1 = close / preclose - 1.0
    gap1 = open_px / preclose - 1.0
    frame["_gap1"] = gap1

    # Smooth-trend efficiency over 20 sessions.
    abs_log_ret = np.log(close / preclose).abs()
    frame["_abs_log_ret"] = abs_log_ret
    path20 = frame.groupby("instrument", sort=False)["_abs_log_ret"].transform(
        lambda s: s.rolling(20, min_periods=15).sum()
    )
    displacement20 = np.log(close / by_stock["close"].shift(20)).abs()
    trend_eff20 = displacement20 / path20.replace(0, np.nan)

    # Existing structural factors.
    frame["f_LOW_VOL10"] = -pd.to_numeric(frame["vol10"], errors="coerce")
    frame["f_PULLBACK5"] = -pd.to_numeric(frame["ret5"], errors="coerce")
    frame["f_TREND_EFF20"] = trend_eff20

    turn_dist = np.where(
        turnover < 3.0, 3.0 - turnover,
        np.where(turnover > 15.0, turnover - 15.0, 0.0),
    )
    frame["f_TURNOVER_SWEET"] = -pd.Series(turn_dist, index=frame.index)
    frame.loc[turnover.isna(), "f_TURNOVER_SWEET"] = np.nan

    # Gap/candle microstructure known at T-1 close.
    frame["f_LOW_ABS_GAP1"] = -gap1.abs()
    day_range = (high - low).replace(0, np.nan)
    frame["f_HIGH_CLOSE_LOC1"] = (close - low) / day_range
    upper_shadow = high - pd.concat([open_px, close], axis=1).max(axis=1)
    frame["f_LOW_UPPER_SHADOW1"] = -(upper_shadow / preclose.replace(0, np.nan))
    frame["f_LOW_AMPLITUDE1"] = -(day_range / preclose.replace(0, np.nan))

    # Activity/liquidity domains.
    turn_base5 = by_stock["turnover_rate_pct"].transform(
        lambda s: pd.to_numeric(s, errors="coerce").shift(1).rolling(5, min_periods=3).mean()
    )
    turn_accel5 = turnover / turn_base5.replace(0, np.nan)
    frame["f_LOW_TURNOVER_ACCEL5"] = -np.log(turn_accel5.clip(lower=1e-6)).abs()
    frame["f_HIGH_LIQUIDITY"] = np.log(amount.where(amount > 0))

    if "float_market_cap_est" in frame.columns:
        cap = pd.to_numeric(frame["float_market_cap_est"], errors="coerce")
        frame["f_SMALLER_FLOAT_CAP"] = -np.log(cap.where(cap > 0))
    else:
        frame["f_SMALLER_FLOAT_CAP"] = np.nan

    # Gap-risk domain: prefer more stable overnight pricing over the prior 10 sessions.
    gap_vol10 = frame.groupby("instrument", sort=False)["_gap1"].transform(
        lambda s: s.rolling(10, min_periods=7).std()
    )
    frame["f_LOW_GAP_VOL10"] = -gap_vol10

    cols = ["date", "instrument"] + [f"f_{name}" for name in FACTORS]
    return (
        frame[cols]
        .rename(columns={"date": "signal_date"})
        .drop_duplicates(["signal_date", "instrument"], keep="last")
    )


def _base_eligible(features: pd.DataFrame) -> pd.DataFrame:
    mask = (
        features["base_executable"]
        & features["limit_gap"].ge(LIMIT_BUFFER)
        & _market_mask(features)
    )
    return features.loc[mask].copy()


def _rank_columns(eligible: pd.DataFrame) -> pd.DataFrame:
    z = eligible.copy()
    by_day = z.groupby("trade_date", sort=False)
    z["r_base"] = by_day["clean_mom20_rank"].rank(pct=True)
    for name in FACTORS:
        z[f"r_{name}"] = by_day[f"f_{name}"].rank(pct=True)
    return z


def _daily_corr_stats(z: pd.DataFrame, a: str, b: str, dev_only: bool = True) -> dict[str, Any]:
    x = z[z["trade_date"] <= DEV_END].copy() if dev_only else z.copy()
    vals: list[float] = []
    for _, g in x[["trade_date", a, b]].dropna().groupby("trade_date", sort=False):
        if len(g) < MIN_CORR_N:
            continue
        c = g[a].corr(g[b], method="pearson")  # Pearson on percentile ranks = Spearman.
        if pd.notna(c):
            vals.append(float(c))
    arr = np.asarray(vals, dtype=float)
    if not len(arr):
        return {"n_dates": 0, "mean_corr": None, "mean_abs_corr": None, "median_abs_corr": None, "p90_abs_corr": None}
    return {
        "n_dates": int(len(arr)),
        "mean_corr": float(arr.mean()),
        "mean_abs_corr": float(np.abs(arr).mean()),
        "median_abs_corr": float(np.median(np.abs(arr))),
        "p90_abs_corr": float(np.quantile(np.abs(arr), 0.90)),
    }


def _residualize_against_base(z: pd.DataFrame, factor: str) -> pd.Series:
    """Cross-sectional OLS residual each day; uses only same-day T-1 information."""
    out = pd.Series(np.nan, index=z.index, dtype=float)
    fcol = f"r_{factor}"
    for _, idx in z.groupby("trade_date", sort=False).groups.items():
        g = z.loc[idx, ["r_base", fcol]].dropna()
        if len(g) < 3:
            continue
        x = g["r_base"].to_numpy(float)
        y = g[fcol].to_numpy(float)
        X = np.column_stack([np.ones(len(x)), x])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        out.loc[g.index] = resid
    return out


def _add_orthogonal_ranks(z: pd.DataFrame) -> pd.DataFrame:
    out = z.copy()
    for name in FACTORS:
        resid_col = f"resid_{name}"
        ortho_col = f"o_{name}"
        out[resid_col] = _residualize_against_base(out, name)
        out[ortho_col] = out.groupby("trade_date", sort=False)[resid_col].rank(pct=True)
    return out


def _evaluate(z: pd.DataFrame, all_dates: list[pd.Timestamp], factors: tuple[str, ...], cost: str, name: str) -> tuple[dict[str, Any], pd.DataFrame]:
    cols = [f"o_{f}" for f in factors]
    y = z.dropna(subset=cols).copy() if cols else z.copy()
    score_cols = ["r_base"] + cols
    y["score"] = y[score_cols].mean(axis=1)
    selected = v43._select_top(y, TOP_N)
    series, ledger = v43._portfolio_series(selected, all_dates, EXIT, cost)
    all_s, all_l = v43._slice(series, ledger, None, None)
    dev_s, dev_l = v43._slice(series, ledger, None, DEV_END)
    oos_s, oos_l = v43._slice(series, ledger, v43.OOS_START, None)
    item = {
        "name": name,
        "factors": list(factors),
        "cost": cost,
        "metrics": {
            "all": v43._metrics(all_s, all_l),
            "development_2021_2023": v43._metrics(dev_s, dev_l),
            "oos_2024_2026": v43._metrics(oos_s, oos_l),
        },
    }
    return item, selected


def _num(m: dict[str, Any], key: str, fallback: float = -999.0) -> float:
    v = m.get(key)
    return fallback if v is None else float(v)


def _mean_daily_top_overlap(a: pd.DataFrame, b: pd.DataFrame) -> float | None:
    if a.empty or b.empty:
        return None
    amap = a.groupby("trade_date")["instrument"].apply(set)
    bmap = b.groupby("trade_date")["instrument"].apply(set)
    dates = amap.index.intersection(bmap.index)
    if not len(dates):
        return None
    vals = [len(amap.loc[d] & bmap.loc[d]) / float(TOP_N) for d in dates]
    return float(np.mean(vals)) if vals else None


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
    factors = _daily_factor_frame()
    features = features.merge(factors, on=["signal_date", "instrument"], how="left", validate="many_to_one")

    if features["base_executable"].any():
        first_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].min())
        last_exec = pd.Timestamp(features.loc[features["base_executable"], "trade_date"].max())
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]

    eligible = _base_eligible(features)
    ranked = _rank_columns(eligible)
    ortho = _add_orthogonal_ranks(ranked)

    # Correlation audit is development-only for selection.
    core_corr: dict[str, Any] = {}
    pair_corr: dict[str, Any] = {}
    corr_rows: list[dict[str, Any]] = []
    for f in FACTORS:
        stats = _daily_corr_stats(ranked, "r_base", f"r_{f}", dev_only=True)
        core_corr[f] = stats
        corr_rows.append({"a": "BASE", "b": f, **stats})
    for i, a in enumerate(FACTORS):
        for b in FACTORS[i + 1:]:
            stats = _daily_corr_stats(ranked, f"r_{a}", f"r_{b}", dev_only=True)
            pair_corr[f"{a}|{b}"] = stats
            corr_rows.append({"a": a, "b": b, **stats})

    results: list[dict[str, Any]] = []
    selected_ledgers: dict[tuple[str, str], pd.DataFrame] = {}
    for cost in COSTS:
        item, ledger = _evaluate(ortho, all_dates, (), cost, "BASELINE")
        results.append(item)
        selected_ledgers[("BASELINE", cost)] = ledger
        for f in FACTORS:
            item, ledger = _evaluate(ortho, all_dates, (f,), cost, f"ORTHO_{f}")
            results.append(item)
            selected_ledgers[(f"ORTHO_{f}", cost)] = ledger

    lookup = {(x["name"], x["cost"]): x for x in results}
    survivors: list[tuple[float, str]] = []
    diagnostics: dict[str, Any] = {}
    for f in FACTORS:
        c = core_corr[f]
        corr_ok = (
            c.get("mean_abs_corr") is not None
            and float(c["mean_abs_corr"]) <= MAX_CORE_MEAN_ABS_CORR
            and float(c["p90_abs_corr"]) <= MAX_CORE_P90_ABS_CORR
        )
        improvements: list[float] = []
        perf_ok = True
        for cost in COSTS:
            base = lookup[("BASELINE", cost)]["metrics"]["development_2021_2023"]
            item = lookup[(f"ORTHO_{f}", cost)]["metrics"]["development_2021_2023"]
            imp = _num(item, "cagr") - _num(base, "cagr")
            improvements.append(imp)
            if imp < MIN_DEV_CAGR_IMPROVEMENT or _num(item, "max_drawdown", -1.0) < _num(base, "max_drawdown", -1.0):
                perf_ok = False
        overlap = _mean_daily_top_overlap(
            selected_ledgers[("BASELINE", "BASE")],
            selected_ledgers[(f"ORTHO_{f}", "BASE")],
        )
        diagnostics[f] = {
            "core_correlation": c,
            "correlation_gate": corr_ok,
            "development_mean_cagr_improvement": float(np.mean(improvements)),
            "performance_gate": perf_ok,
            "baseline_top3_overlap": overlap,
        }
        if corr_ok and perf_ok:
            survivors.append((float(np.mean(improvements)), f))

    survivors.sort(reverse=True)
    chosen: list[str] = []
    for _, f in survivors:
        pair_ok = True
        for prev in chosen:
            key = f"{prev}|{f}" if f"{prev}|{f}" in pair_corr else f"{f}|{prev}"
            s = pair_corr.get(key, {})
            if s.get("mean_abs_corr") is None or float(s["mean_abs_corr"]) > MAX_PAIR_MEAN_ABS_CORR:
                pair_ok = False
                break
        if pair_ok:
            chosen.append(f)
        if len(chosen) >= 2:
            break

    if chosen:
        combo = tuple(chosen)
        combo_name = "ORTHO_COMBO_" + "_".join(chosen)
        for cost in COSTS:
            item, ledger = _evaluate(ortho, all_dates, combo, cost, combo_name)
            results.append(item)
            selected_ledgers[(combo_name, cost)] = ledger

    report = {
        "question": "Can weakly-correlated, cross-sectionally orthogonal T-1 factors add robust information to LIMIT_ADJUSTED_MOMENTUM?",
        "preregistration": {
            "base": "LIMIT_ADJUSTED_MOMENTUM + breadth5>0 + money_effect>0 + Top3 + T14:45/T+1 10:00",
            "development": "2021-2023 only",
            "oos": "2024-2026 untouched for selection",
            "correlation_measure": "daily cross-sectional Spearman (Pearson on percentile ranks)",
            "core_gate": {"mean_abs_corr_max": MAX_CORE_MEAN_ABS_CORR, "p90_abs_corr_max": MAX_CORE_P90_ABS_CORR},
            "pair_gate": {"mean_abs_corr_max": MAX_PAIR_MEAN_ABS_CORR},
            "performance_gate": f">={MIN_DEV_CAGR_IMPROVEMENT:.2%} CAGR improvement and no worse MDD under BASE and CONSERVATIVE",
            "orthogonalization": "daily OLS residual of factor percentile rank on clean-momentum percentile rank; residual reranked cross-sectionally",
            "weights": "equal weight r_base and each selected orthogonal rank; no optimization",
        },
        "factor_definitions": {
            "LOW_VOL10": "lower 10d daily-return volatility",
            "PULLBACK5": "lower recent 5d return inside the already-strong 20d universe",
            "TREND_EFF20": "higher 20d displacement/path efficiency",
            "TURNOVER_SWEET": "closer to pre-registered 3%-15% turnover interval",
            "LOW_ABS_GAP1": "smaller absolute T-1 opening gap",
            "HIGH_CLOSE_LOC1": "T-1 close nearer top of daily range",
            "LOW_UPPER_SHADOW1": "smaller T-1 upper shadow relative to preclose",
            "LOW_AMPLITUDE1": "smaller T-1 high-low range relative to preclose",
            "LOW_TURNOVER_ACCEL5": "T-1 turnover closer to its prior-5d mean",
            "HIGH_LIQUIDITY": "higher log T-1 traded amount",
            "SMALLER_FLOAT_CAP": "lower log float market cap",
            "LOW_GAP_VOL10": "lower rolling 10d opening-gap volatility",
        },
        "coverage": {
            "eligible_rows": int(len(eligible)),
            "eligible_dates": int(eligible["trade_date"].nunique()),
            "factor_non_null_fraction": {f: float(eligible[f"f_{f}"].notna().mean()) for f in FACTORS},
        },
        "core_correlations_dev": core_corr,
        "pair_correlations_dev": pair_corr,
        "factor_diagnostics_dev": diagnostics,
        "development_survivors_ranked": [f for _, f in survivors],
        "development_selected_weak_corr_combo": chosen,
        "results": results,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _flat_rows(results).to_csv(RESULT_CSV, index=False)
    pd.DataFrame(corr_rows).to_csv(CORR_CSV, index=False)
    print(json.dumps({
        "survivors": [f for _, f in survivors],
        "chosen": chosen,
        "diagnostics": diagnostics,
        "combo_oos": [x for x in results if x["name"].startswith("ORTHO_COMBO") and x["cost"] == "BASE"],
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
