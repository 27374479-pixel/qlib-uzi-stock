"""V4.8 long-only/cash market-gate validation.

Fixed deployable question:
- X02 LIMIT_ADJUSTED_MOMENTUM signal from T-1 close
- A-share long-only or cash; no shorting/derivatives
- Top5 equal weight
- enter T 14:45 close
- exit T+1 10:00 close
- 0.5% limit buffer
- BASE transaction costs for model target, plus conservative cost stress

This script falsifies gate hypotheses one by one and does not tune thresholds
on the evaluation data. Same-day ML features stop at 14:40 so the 14:45
execution price is strictly later than the feature cutoff.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, RidgeClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import v4_3_long_only_portfolio as v43

ROOT = Path(__file__).resolve().parent
OUTPUT_JSON = ROOT / "output" / "v4_8_long_only_gate_validation.json"
OUTPUT_CSV = ROOT / "output" / "v4_8_long_only_gate_validation.csv"

TOP_N = 5
LIMIT_BUFFER = 0.005
EXIT = "10:00"
MIN_TRAIN = 180
BOOTSTRAP_SAMPLES = 2000
PLACEBO_SAMPLES = 2000
SEED = 20260906
POST_AUG_START = pd.Timestamp("2026-08-01")
FEATURE_CUTOFF = "14:40"

SIMPLE_GATES = (
    "NOT_WEAK",
    "BREADTH_POS",
    "BREADTH5_POS",
    "MONEY_POS",
    "BREADTH_AND_MONEY",
    "BREADTH5_AND_MONEY",
    "STRONG_ALL",
)

MODEL_FEATURES = (
    "frozen_breadth",
    "frozen_breadth5",
    "frozen_money_effect",
    "frozen_weak_market",
    "market_ret_1440",
    "advance_ratio_1440",
    "breadth5_1440",
    "breadth5_delta",
    "morning_to_afternoon",
    "tail_strength",
    "amount_ratio20",
    "trend5_prev",
    "trend20_prev",
    "near_limit_up_ratio",
    "near_limit_down_ratio",
)


def _active_dates(ledger: pd.DataFrame) -> pd.DatetimeIndex:
    if ledger.empty:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(pd.to_datetime(ledger["trade_date"]).dt.normalize().unique()).sort_values()


def _filter_ledger(ledger: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    keep = set(pd.DatetimeIndex(dates))
    return ledger[pd.to_datetime(ledger["trade_date"]).dt.normalize().isin(keep)].copy()


def _period_metrics(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, start, end in (
        ("all", None, None),
        ("development_2021_2023", None, v43.OOS_START - pd.Timedelta(days=1)),
        ("oos_2024_2026", v43.OOS_START, None),
        ("pre_aug_2026", None, POST_AUG_START - pd.Timedelta(days=1)),
        ("post_aug_2026", POST_AUG_START, None),
    ):
        s, l = v43._slice(series, ledger, start, end)
        out[name] = v43._metrics(s, l)
    return out


def _simple_gate_table(candidates: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "trade_date", "breadth", "breadth5", "money_effect", "signal_weak_market"
    ]
    d = candidates[cols].copy()
    d["trade_date"] = pd.to_datetime(d["trade_date"]).dt.normalize()
    d = d.sort_values("trade_date").groupby("trade_date", as_index=False).first()
    d = d.set_index("trade_date").sort_index()
    weak = d["signal_weak_market"].fillna(True).astype(bool)
    b = pd.to_numeric(d["breadth"], errors="coerce")
    b5 = pd.to_numeric(d["breadth5"], errors="coerce")
    money = pd.to_numeric(d["money_effect"], errors="coerce")
    out = pd.DataFrame(index=d.index)
    out["NOT_WEAK"] = ~weak
    out["BREADTH_POS"] = b > 0
    out["BREADTH5_POS"] = b5 > 0
    out["MONEY_POS"] = money > 0
    out["BREADTH_AND_MONEY"] = (b > 0) & (money > 0)
    out["BREADTH5_AND_MONEY"] = (b5 > 0) & (money > 0)
    out["STRONG_ALL"] = (~weak) & (b5 > 0) & (money > 0)
    return out.astype(bool)


def _market_intraday_features() -> pd.DataFrame:
    missing = [str(p) for p in v43.MINUTE_FILES if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing persisted minute files: {missing}")
    files_sql = ",".join(
        "'" + str(p.resolve()).replace("'", "''") + "'" for p in v43.MINUTE_FILES
    )
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    q = f"""
    WITH bars AS (
      SELECT
        CAST(datetime AS DATE) AS date,
        instrument,
        MAX(CASE WHEN strftime(datetime, '%H:%M')='09:35' THEN open END) AS day_open,
        MAX(CASE WHEN strftime(datetime, '%H:%M')='11:30' THEN close END) AS px_1130,
        MAX(CASE WHEN strftime(datetime, '%H:%M')='14:30' THEN close END) AS px_1430,
        MAX(CASE WHEN strftime(datetime, '%H:%M')='{FEATURE_CUTOFF}' THEN close END) AS px_1440,
        MAX(CASE WHEN strftime(datetime, '%H:%M')='15:00' THEN close END) AS px_1500,
        SUM(CASE WHEN strftime(datetime, '%H:%M')<='{FEATURE_CUTOFF}'
                 THEN COALESCE(amount,0) ELSE 0 END) AS amount_1440
      FROM read_parquet([{files_sql}])
      WHERE UPPER(instrument) NOT LIKE 'SH688%'
      GROUP BY 1,2
    ),
    lagged AS (
      SELECT *,
        LAG(px_1500) OVER (PARTITION BY instrument ORDER BY date) AS prev_close
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


def _frozen_features(candidates: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "trade_date", "breadth", "breadth5", "money_effect", "signal_weak_market"
    ]
    d = candidates[cols].copy()
    d["trade_date"] = pd.to_datetime(d["trade_date"]).dt.normalize()
    d = d.sort_values("trade_date").groupby("trade_date", as_index=False).first()
    d = d.set_index("trade_date").sort_index()
    return d.rename(columns={
        "breadth": "frozen_breadth",
        "breadth5": "frozen_breadth5",
        "money_effect": "frozen_money_effect",
        "signal_weak_market": "frozen_weak_market",
    })


def _walk_forward_gate(
    frame: pd.DataFrame,
    model_name: str,
) -> tuple[pd.Series, pd.Series, list[dict[str, Any]]]:
    pred = pd.Series(pd.NA, index=frame.index, dtype="boolean")
    score = pd.Series(np.nan, index=frame.index, dtype=float)
    refits: list[dict[str, Any]] = []

    for month, test in frame.groupby(frame.index.to_period("M"), sort=True):
        month_start = month.start_time
        train = frame.loc[frame.index < month_start].dropna(
            subset=[*MODEL_FEATURES, "target_up"]
        )
        test_valid = test.dropna(subset=list(MODEL_FEATURES))
        if len(train) < MIN_TRAIN or len(test_valid) == 0:
            continue
        y = train["target_up"].astype(int)
        if y.nunique() < 2:
            continue
        X = train.loc[:, MODEL_FEATURES].astype(float)
        Xt = test_valid.loc[:, MODEL_FEATURES].astype(float)
        if model_name == "LOGISTIC":
            model = make_pipeline(
                StandardScaler(),
                LogisticRegression(
                    C=1.0, penalty="l2", solver="lbfgs",
                    max_iter=2000, random_state=SEED
                ),
            )
            model.fit(X, y)
            p = model.predict_proba(Xt)[:, 1]
            score.loc[Xt.index] = p
            pred.loc[Xt.index] = p > 0.50
            threshold = 0.50
        elif model_name == "RIDGE":
            model = make_pipeline(StandardScaler(), RidgeClassifier(alpha=1.0))
            model.fit(X, y)
            s = model.decision_function(Xt)
            score.loc[Xt.index] = s
            pred.loc[Xt.index] = s > 0.0
            threshold = 0.0
        else:
            raise ValueError(model_name)
        refits.append({
            "month": str(month),
            "train_n": int(len(train)),
            "train_start": str(train.index.min().date()),
            "train_end": str(train.index.max().date()),
            "train_positive_rate": float(y.mean()),
            "test_n": int(len(test_valid)),
            "threshold": threshold,
        })
    return pred, score, refits


def _block_bootstrap_diff(
    returns: pd.Series,
    gate: pd.Series,
    seed: int,
) -> dict[str, Any]:
    x = pd.to_numeric(returns, errors="coerce")
    g = gate.reindex(x.index).astype("boolean")
    ok = x.notna() & g.notna()
    x = x.loc[ok].to_numpy(float)
    gg = g.loc[ok].astype(bool).to_numpy()
    if gg.sum() < 8 or (~gg).sum() < 8:
        return {"n": int(len(x)), "ci95": [None, None], "bootstrap_samples": 0}
    observed = float(x[gg].mean() - x[~gg].mean())
    rng = np.random.default_rng(seed)
    n = len(x)
    block = 5
    vals = np.empty(BOOTSTRAP_SAMPLES, dtype=float)
    for b in range(BOOTSTRAP_SAMPLES):
        idx_parts = []
        total = 0
        while total < n:
            start = int(rng.integers(0, max(1, n - block + 1)))
            part = np.arange(start, min(start + block, n))
            idx_parts.append(part)
            total += len(part)
        idx = np.concatenate(idx_parts)[:n]
        xb = x[idx]
        gb = gg[idx]
        if gb.sum() == 0 or (~gb).sum() == 0:
            vals[b] = np.nan
        else:
            vals[b] = xb[gb].mean() - xb[~gb].mean()
    vals = vals[np.isfinite(vals)]
    return {
        "n": int(n),
        "observed_mean_diff": observed,
        "ci95": [
            float(np.quantile(vals, 0.025)) if len(vals) else None,
            float(np.quantile(vals, 0.975)) if len(vals) else None,
        ],
        "bootstrap_samples": int(len(vals)),
    }


def _conditional_quality(
    base_active_returns: pd.Series,
    gate: pd.Series,
    seed: int,
) -> dict[str, Any]:
    x = pd.to_numeric(base_active_returns, errors="coerce")
    g = gate.reindex(x.index).astype("boolean")
    ok = x.notna() & g.notna()
    x = x.loc[ok]
    g = g.loc[ok].astype(bool)
    on = x[g]
    off = x[~g]
    out = {
        "defined_days": int(len(x)),
        "on_days": int(len(on)),
        "off_days": int(len(off)),
        "on_mean": float(on.mean()) if len(on) else None,
        "off_mean": float(off.mean()) if len(off) else None,
        "on_win_rate": float((on > 0).mean()) if len(on) else None,
        "off_win_rate": float((off > 0).mean()) if len(off) else None,
        "mean_diff": float(on.mean() - off.mean()) if len(on) and len(off) else None,
        "by_year": {},
    }
    for year in sorted(x.index.year.unique()):
        yy = x.index.year == year
        xy = x[yy]
        gy = g[yy]
        on_y, off_y = xy[gy], xy[~gy]
        out["by_year"][str(int(year))] = {
            "on_n": int(len(on_y)),
            "off_n": int(len(off_y)),
            "on_mean": float(on_y.mean()) if len(on_y) else None,
            "off_mean": float(off_y.mean()) if len(off_y) else None,
            "mean_diff": float(on_y.mean() - off_y.mean()) if len(on_y) and len(off_y) else None,
        }
    out["block_bootstrap_mean_diff"] = _block_bootstrap_diff(x, g, seed)
    return out


def _placebo(
    base_active_returns: pd.Series,
    gate: pd.Series,
    seed: int,
) -> dict[str, Any]:
    x = pd.to_numeric(base_active_returns, errors="coerce")
    g = gate.reindex(x.index).astype("boolean")
    ok = x.notna() & g.notna()
    x = x.loc[ok]
    g = g.loc[ok].astype(bool)
    if g.sum() < 5:
        return {"samples": 0}
    actual = float(x[g].mean())
    rng = np.random.default_rng(seed)
    vals = np.empty(PLACEBO_SAMPLES, dtype=float)
    years = sorted(x.index.year.unique())
    for i in range(PLACEBO_SAMPLES):
        chosen_parts: list[pd.DatetimeIndex] = []
        for year in years:
            dates_y = x.index[x.index.year == year]
            n_on = int(g.loc[dates_y].sum())
            if n_on <= 0:
                continue
            n_on = min(n_on, len(dates_y))
            chosen_parts.append(
                pd.DatetimeIndex(rng.choice(dates_y.to_numpy(), size=n_on, replace=False))
            )
        if not chosen_parts:
            vals[i] = np.nan
            continue
        chosen = chosen_parts[0]
        for part in chosen_parts[1:]:
            chosen = chosen.append(part)
        vals[i] = float(x.loc[chosen].mean())
    vals = vals[np.isfinite(vals)]
    return {
        "samples": int(len(vals)),
        "actual_on_mean": actual,
        "random_mean_median": float(np.median(vals)) if len(vals) else None,
        "random_mean_95": [
            float(np.quantile(vals, 0.025)) if len(vals) else None,
            float(np.quantile(vals, 0.975)) if len(vals) else None,
        ],
        "p_random_ge_actual": float(np.mean(vals >= actual)) if len(vals) else None,
        "percentile_vs_random": float(np.mean(vals < actual)) if len(vals) else None,
    }


def _gate_result(
    name: str,
    gate: pd.Series,
    series_by_cost: dict[str, pd.Series],
    ledger_by_cost: dict[str, pd.DataFrame],
    base_active_returns: pd.Series,
    seed: int,
) -> dict[str, Any]:
    gate = gate.astype("boolean")
    out: dict[str, Any] = {
        "name": name,
        "gate_defined_days": int(gate.notna().sum()),
        "gate_on_days": int(gate.fillna(False).sum()),
        "conditional_base_quality": _conditional_quality(base_active_returns, gate, seed),
        "matched_frequency_placebo": _placebo(base_active_returns, gate, seed + 10000),
        "costs": {},
    }
    on_dates = pd.DatetimeIndex(gate.index[gate.fillna(False)])
    for cost, base_series in series_by_cost.items():
        live = base_series.where(
            pd.Series(base_series.index.isin(on_dates), index=base_series.index),
            0.0,
        )
        live_ledger = _filter_ledger(ledger_by_cost[cost], on_dates)
        out["costs"][cost] = _period_metrics(live, live_ledger)
    return out


def run() -> dict[str, Any]:
    candidates, all_dates = v43._prepare_candidates()
    minute = v43._minute_extract(candidates)
    features = v43._add_intraday_features(candidates, minute)

    if features["base_executable"].any():
        first_exec = pd.Timestamp(
            features.loc[features["base_executable"], "trade_date"].min()
        ).normalize()
        last_exec = pd.Timestamp(
            features.loc[features["base_executable"], "trade_date"].max()
        ).normalize()
        all_dates = [d for d in all_dates if first_exec <= d <= last_exec]

    eligible = features[
        features["base_executable"] & features["limit_gap"].ge(LIMIT_BUFFER)
    ].copy()
    eligible["score"] = eligible["clean_mom20_rank"].fillna(-np.inf)
    selected = v43._select_top(eligible, TOP_N)

    series_by_cost: dict[str, pd.Series] = {}
    ledger_by_cost: dict[str, pd.DataFrame] = {}
    for cost in ("BASE", "CONSERVATIVE"):
        s, l = v43._portfolio_series(selected, all_dates, EXIT, cost)
        series_by_cost[cost] = s
        ledger_by_cost[cost] = l

    active_dates = _active_dates(ledger_by_cost["BASE"])
    base_active_returns = series_by_cost["BASE"].reindex(active_dates)

    report: dict[str, Any] = {
        "question": (
            "Can causal market-state gating make V4.2 LIMIT_ADJUSTED_MOMENTUM "
            "an investable A-share long-only/cash strategy?"
        ),
        "preregistered_spec": {
            "positioning": "long-only or 100% cash; no shorting, margin short, futures or options",
            "signal": "X02 LIMIT_ADJUSTED_MOMENTUM fixed at T-1 close",
            "selected_rule": "raw_mom20_rank>=0.80 & clean_mom20_rank>=0.80 & hit_count20<=1",
            "entry": "T 14:45 close",
            "exit": "T+1 10:00 close",
            "top_n": TOP_N,
            "weighting": "equal weight",
            "limit_buffer": LIMIT_BUFFER,
            "base_cost": "commission 2.5bp/side + slippage 5bp/side + historical sell stamp duty",
            "conservative_cost": "commission 3bp/side + slippage 10bp/side + historical sell stamp duty",
            "simple_gate_information_time": "T-1 close only",
            "ml_feature_cutoff": "T 14:40, strictly before 14:45 entry",
            "ml_target": "BASE-cost Top5 basket net return from T 14:45 to T+1 10:00 > 0",
            "ml_refit": "expanding window, once per calendar month, fixed thresholds",
            "logistic_threshold": 0.50,
            "ridge_threshold": 0.0,
            "min_train_active_days": MIN_TRAIN,
            "no_hyperparameter_search": True,
        },
        "coverage": {
            "candidate_rows": int(len(candidates)),
            "base_executable_rows": int(features["base_executable"].sum()),
            "selected_rows": int(len(selected)),
            "active_trade_days": int(len(active_dates)),
            "actual_trade_start": str(active_dates.min().date()) if len(active_dates) else None,
            "actual_trade_end": str(active_dates.max().date()) if len(active_dates) else None,
        },
        "baseline": {
            cost: _period_metrics(series_by_cost[cost], ledger_by_cost[cost])
            for cost in ("BASE", "CONSERVATIVE")
        },
        "simple_gates": {},
        "walk_forward_gates": {},
        "holdout_note": (
            "2026-08 onward is reported as a post-August slice, NOT a pristine untouched "
            "holdout: earlier V4.3/V4.4 code already used data through 2026-09-03. "
            "A truly untouched future holdout must begin after 2026-09-03."
        ),
    }

    simple = _simple_gate_table(candidates)
    for i, name in enumerate(SIMPLE_GATES):
        gate = simple[name].reindex(active_dates).astype("boolean")
        report["simple_gates"][name] = _gate_result(
            name, gate, series_by_cost, ledger_by_cost,
            base_active_returns, SEED + i * 100
        )

    intraday = _market_intraday_features()
    frozen = _frozen_features(candidates)
    model_frame = pd.DataFrame(index=active_dates)
    model_frame = model_frame.join(frozen, how="left").join(intraday, how="left")
    model_frame["frozen_weak_market"] = (
        model_frame["frozen_weak_market"].astype("boolean").astype(float)
    )
    model_frame["base_net_return"] = base_active_returns
    model_frame["target_up"] = (model_frame["base_net_return"] > 0).astype(float)

    feature_missing = {
        c: int(model_frame[c].isna().sum()) for c in MODEL_FEATURES
    }
    report["ml_feature_coverage"] = {
        "active_days": int(len(model_frame)),
        "feature_missing_counts": feature_missing,
        "complete_feature_days": int(model_frame.loc[:, MODEL_FEATURES].notna().all(axis=1).sum()),
        "features": list(MODEL_FEATURES),
    }

    for i, model_name in enumerate(("LOGISTIC", "RIDGE")):
        gate, score, refits = _walk_forward_gate(model_frame, model_name)
        item = _gate_result(
            model_name, gate, series_by_cost, ledger_by_cost,
            base_active_returns, SEED + 1000 + i * 100
        )
        item["refits"] = refits
        item["first_defined_date"] = (
            str(gate.dropna().index.min().date()) if gate.notna().any() else None
        )
        item["last_defined_date"] = (
            str(gate.dropna().index.max().date()) if gate.notna().any() else None
        )
        item["score_summary"] = {
            "mean": float(score.dropna().mean()) if score.notna().any() else None,
            "std": float(score.dropna().std(ddof=1)) if score.notna().sum() > 1 else None,
        }
        report["walk_forward_gates"][model_name] = item

    rows = []
    base_m = report["baseline"]["BASE"]["all"]
    rows.append({
        "strategy": "BASELINE_ALL",
        "cagr": base_m.get("cagr"),
        "max_drawdown": base_m.get("max_drawdown"),
        "sharpe": base_m.get("sharpe"),
        "mean_active_day": base_m.get("mean_active_day"),
        "active_win_rate": base_m.get("active_win_rate"),
        "post_aug_2026_return": report["baseline"]["BASE"]["post_aug_2026"].get("total_return"),
        "placebo_p": np.nan,
        "on_minus_off_mean": np.nan,
    })
    for family in ("simple_gates", "walk_forward_gates"):
        for name, item in report[family].items():
            m = item["costs"]["BASE"]["all"]
            cq = item["conditional_base_quality"]
            rows.append({
                "strategy": name,
                "cagr": m.get("cagr"),
                "max_drawdown": m.get("max_drawdown"),
                "sharpe": m.get("sharpe"),
                "mean_active_day": m.get("mean_active_day"),
                "active_win_rate": m.get("active_win_rate"),
                "post_aug_2026_return": item["costs"]["BASE"]["post_aug_2026"].get("total_return"),
                "placebo_p": item["matched_frequency_placebo"].get("p_random_ge_actual"),
                "on_minus_off_mean": cq.get("mean_diff"),
            })
    summary = pd.DataFrame(rows).sort_values("cagr", ascending=False)

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    summary.to_csv(OUTPUT_CSV, index=False)

    print(summary.to_string(index=False))
    print(json.dumps({
        "coverage": report["coverage"],
        "holdout_note": report["holdout_note"],
        "top_by_cagr": summary.head(10).to_dict(orient="records"),
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
