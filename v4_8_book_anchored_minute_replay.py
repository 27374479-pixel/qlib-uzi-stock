"""V4.8 book-anchored minute replay.

This stage is source constrained: every tested overlay must map to a hypothesis
already registered in BOOK_ALPHA_HYPOTHESIS_REGISTRY.md.  Generic quant factors
may be used as an external control/challenger, but cannot enter this script as a
new strategy rule without a book hypothesis ID.

Book hypotheses tested here:
- H03 climax avoidance: completed T-1 climax state is a veto, not a rank factor.
- H16 low-open-reclaim: T low/open divergence followed by reclaim of VWAP/prev close.
- H17 first-divergence-reclaim: prior core identity exists, one main below-VWAP
  episode is released and a completed bar reclaims VWAP; delay 5/10m must survive.
- H18 late-chase/one-word avoidance: T-1 one-word and T near/at upper limit are vetoes.

The existing LIMIT_ADJUSTED_MOMENTUM module is retained only as the externally
validated *candidate core*.  It is explicitly not attributed to a trader/book.
The book-derived modules here are overlays on top of that core.

This is exploratory causal replay, not pristine OOS: the operationalization was
implemented after earlier 2021-2026 research.  Every historical decision is
still point-in-time causal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import v4_3_long_only_portfolio as v43
from external_challenger_daily_screen import challenger_masks

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_8_book_anchored_minute_replay.json"
CSV_OUTPUT = ROOT / "output" / "v4_8_book_anchored_minute_replay.csv"
LEDGER_OUTPUT = ROOT / "output" / "v4_8_book_anchored_minute_ledger.csv"

MINUTE_FILES = v43.MINUTE_FILES
SAMPLE_START = v43.SAMPLE_START
LIMIT_BUFFER = 0.005
TOP_N = 3
EXIT_TIME = "10:00"
ENTRY_TIMES = ("14:45", "14:50", "14:55")
COSTS = ("BASE", "CONSERVATIVE")

BOOK_SOURCE = {
    "H03": {
        "title": "climax avoidance",
        "source_cluster": "情绪周期/高潮后分歧",
        "role": "RISK_VETO",
        "operationalization": "exclude candidates whose completed T-1 theme state is climax",
    },
    "H16": {
        "title": "low-open-reclaim",
        "source_cluster": "弱转强/低开拉升/分歧后承接",
        "role": "MINUTE_TRIGGER",
        "operationalization": "T opens below prior close, then completed bars reclaim cumulative VWAP or prior close by 14:45",
    },
    "H17": {
        "title": "first-divergence-reclaim",
        "source_cluster": "炒股养家/乔帮主/涅槃重升",
        "role": "MINUTE_TRIGGER",
        "operationalization": "prior core identity + exactly one below-cumulative-VWAP episode before a completed reclaim by 14:45; test +5/+10m entry delay",
    },
    "H18": {
        "title": "late-chase / one-word avoidance",
        "source_cluster": "一字板买不到/高潮不追/涨停不是买点",
        "role": "EXECUTION_VETO",
        "operationalization": "exclude T-1 one-word and T entry at/within 0.5% of upper limit",
    },
}

VARIANTS = (
    "BASELINE_H18",
    "H03_VETO",
    "H16_VWAP_RECLAIM",
    "H16_PREVCLOSE_RECLAIM",
    "H17_FIRST_RECLAIM",
    "H03_H17_FIRST_RECLAIM",
)


def _next_map(frame: pd.DataFrame) -> dict[pd.Timestamp, pd.Timestamp]:
    dates = sorted(pd.to_datetime(frame["date"]).dt.normalize().drop_duplicates())
    return {dates[i]: dates[i + 1] for i in range(len(dates) - 1)}


def _prepare_candidates() -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    cfg = v43.base.Config(start="2015-01-01", end="2026-09-03")
    frame = v43.survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    for required in ("climax", "one_word", "breadth5", "money_effect", "upper_limit", "preclose"):
        if required not in frame.columns:
            raise RuntimeError(f"book replay requires daily field {required}")

    selected = challenger_masks(frame)["X02_limit_adjusted_momentum"]["selected"].fillna(False)
    # Keep the frozen market gate used in V4.4/V4.5.  This gate is not claimed
    # as a book factor in this stage; it is the fixed base context.
    selected &= frame["breadth5"].fillna(-1).gt(0) & frame["money_effect"].fillna(-1).gt(0)

    cols = [
        "date", "instrument", "close", "preclose", "upper_limit", "lower_limit",
        "raw_mom20_rank", "clean_mom20_rank", "hit_count20",
        "breadth", "breadth5", "money_effect", "weak_market",
        "climax", "one_word",
    ]
    for optional in ("trade_status", "is_st"):
        if optional in frame.columns:
            cols.append(optional)
    x = frame.loc[selected, cols].copy().rename(columns={
        "date": "signal_date",
        "close": "signal_close",
        "preclose": "signal_preclose",
        "upper_limit": "signal_upper_limit",
        "lower_limit": "signal_lower_limit",
        "climax": "signal_climax",
        "one_word": "signal_one_word",
        "weak_market": "signal_weak_market",
    })

    nxt = _next_map(frame)
    x["trade_date"] = x["signal_date"].map(nxt)
    x["exit_date"] = x["trade_date"].map(nxt)
    x = x.dropna(subset=["trade_date", "exit_date"]).copy()
    x["trade_date"] = pd.to_datetime(x["trade_date"]).dt.normalize()
    x["exit_date"] = pd.to_datetime(x["exit_date"]).dt.normalize()
    x = x[x["trade_date"] >= SAMPLE_START].copy()
    x = x[~x["instrument"].astype(str).str.upper().str.startswith("SH688")].copy()

    # T-day point-in-time reference fields.
    ref_cols = ["date", "instrument", "preclose", "upper_limit", "lower_limit"]
    for optional in ("trade_status", "is_st"):
        if optional in frame.columns:
            ref_cols.append(optional)
    ref = frame[ref_cols].rename(columns={"date": "trade_date"}).copy()
    x = x.merge(ref, on=["trade_date", "instrument"], how="left", validate="many_to_one", suffixes=("", "_trade"))
    if "trade_status_trade" in x.columns:
        x = x[x["trade_status_trade"].fillna(0).eq(1)]
    elif "trade_status" in x.columns:
        x = x[x["trade_status"].fillna(0).eq(1)]
    if "is_st_trade" in x.columns:
        x = x[x["is_st_trade"].fillna(1).eq(0)]
    elif "is_st" in x.columns:
        x = x[x["is_st"].fillna(1).eq(0)]

    x = x.drop_duplicates(["trade_date", "instrument"]).reset_index(drop=True)
    all_dates = [
        pd.Timestamp(d) for d in sorted(frame["date"].drop_duplicates())
        if pd.Timestamp(d) >= SAMPLE_START and pd.Timestamp(d) <= x["trade_date"].max()
    ]
    return x, all_dates


def _load_minute_path(candidates: pd.DataFrame) -> pd.DataFrame:
    missing = [str(p) for p in MINUTE_FILES if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing persisted minute files: {missing}")
    keys = candidates[["trade_date", "exit_date", "instrument"]].drop_duplicates().copy()
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.register("cand", keys)
    files_sql = ",".join("'" + str(p.resolve()).replace("'", "''") + "'" for p in MINUTE_FILES)
    q = f"""
    SELECT
      CAST(c.trade_date AS DATE) AS trade_date,
      CAST(c.exit_date AS DATE) AS exit_date,
      c.instrument,
      m.datetime,
      m.open, m.high, m.low, m.close, m.volume, m.amount,
      CASE WHEN CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE) THEN 'TRADE' ELSE 'EXIT' END AS session
    FROM cand c
    JOIN read_parquet([{files_sql}]) m
      ON m.instrument=c.instrument
     AND (
          (CAST(m.datetime AS DATE)=CAST(c.trade_date AS DATE)
           AND strftime(m.datetime, '%H:%M') BETWEEN '09:35' AND '14:55')
          OR
          (CAST(m.datetime AS DATE)=CAST(c.exit_date AS DATE)
           AND strftime(m.datetime, '%H:%M')='10:00')
     )
    """
    out = con.execute(q).df()
    con.close()
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    out["exit_date"] = pd.to_datetime(out["exit_date"])
    out["datetime"] = pd.to_datetime(out["datetime"])
    for c in ("open", "high", "low", "close", "volume", "amount"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.sort_values(["trade_date", "instrument", "datetime"])


def _episodes(mask: pd.Series) -> int:
    b = mask.fillna(False).astype(bool)
    prev = b.shift(1, fill_value=False)
    return int((b & ~prev).sum())


def _path_features(candidates: pd.DataFrame, minute: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    trade = minute[minute["session"] == "TRADE"].copy()
    exit_rows = minute[minute["session"] == "EXIT"].copy()
    exit_map = (
        exit_rows.sort_values("datetime")
        .drop_duplicates(["exit_date", "instrument"], keep="last")
        .set_index(["exit_date", "instrument"])["close"]
        .to_dict()
    )
    ref = candidates.set_index(["trade_date", "instrument"])

    for (d, inst), g in trade.groupby(["trade_date", "instrument"], sort=False):
        if (d, inst) not in ref.index:
            continue
        r = ref.loc[(d, inst)]
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        g = g.sort_values("datetime").copy()
        g["time"] = g["datetime"].dt.strftime("%H:%M")
        g = g[g["time"] <= "14:55"].copy()
        if g.empty:
            continue
        vol = g["volume"].fillna(0).clip(lower=0)
        g["cum_vwap_proxy"] = (g["close"] * vol).cumsum() / vol.cumsum().replace(0, np.nan)
        g["below_vwap"] = g["close"] < g["cum_vwap_proxy"]
        upto_1445 = g[g["time"] <= "14:45"].copy()
        if upto_1445.empty:
            continue
        had_below = bool(upto_1445["below_vwap"].iloc[:-1].any()) if len(upto_1445) > 1 else False
        episodes = _episodes(upto_1445["below_vwap"])
        reclaimed = (~upto_1445["below_vwap"]) & upto_1445["below_vwap"].shift(1, fill_value=False)
        reclaim_times = upto_1445.loc[reclaimed, "time"]
        first_reclaim_time = str(reclaim_times.iloc[0]) if len(reclaim_times) else None

        def px(t: str) -> float | None:
            s = g.loc[g["time"] == t, "close"]
            return float(s.iloc[-1]) if len(s) and pd.notna(s.iloc[-1]) else None

        open_s = g.loc[g["time"] == "09:35", "open"]
        day_open = float(open_s.iloc[-1]) if len(open_s) and pd.notna(open_s.iloc[-1]) else None
        p1445 = px("14:45")
        p1450 = px("14:50")
        p1455 = px("14:55")
        vw1445_s = upto_1445.loc[upto_1445["time"] == "14:45", "cum_vwap_proxy"]
        vw1445 = float(vw1445_s.iloc[-1]) if len(vw1445_s) and pd.notna(vw1445_s.iloc[-1]) else None
        preclose = float(r["preclose"]) if pd.notna(r.get("preclose")) else None
        upper = float(r["upper_limit"]) if pd.notna(r.get("upper_limit")) else None
        exit_px = exit_map.get((pd.Timestamp(r["exit_date"]), inst))

        rows.append({
            "trade_date": pd.Timestamp(d),
            "exit_date": pd.Timestamp(r["exit_date"]),
            "instrument": inst,
            "day_open": day_open,
            "entry_1445": p1445,
            "entry_1450": p1450,
            "entry_1455": p1455,
            "vwap_proxy_1445": vw1445,
            "had_below_vwap_before_1445": had_below,
            "below_vwap_episode_count": episodes,
            "first_reclaim_time": first_reclaim_time,
            "reclaim_by_1445": bool(first_reclaim_time is not None and first_reclaim_time <= "14:45" and p1445 is not None and vw1445 is not None and p1445 >= vw1445),
            "low_open": bool(day_open is not None and preclose is not None and day_open < preclose),
            "reclaim_prevclose_1445": bool(p1445 is not None and preclose is not None and p1445 >= preclose),
            "upper_limit": upper,
            "exit_1000": float(exit_px) if exit_px is not None and pd.notna(exit_px) else np.nan,
        })
    out = pd.DataFrame(rows)
    return candidates.merge(out, on=["trade_date", "exit_date", "instrument"], how="left")


def _entry_col(t: str) -> str:
    return {"14:45": "entry_1445", "14:50": "entry_1450", "14:55": "entry_1455"}[t]


def _book_mask(x: pd.DataFrame, variant: str) -> pd.Series:
    h18 = ~x["signal_one_word"].fillna(False).astype(bool)
    if variant == "BASELINE_H18":
        return h18
    if variant == "H03_VETO":
        return h18 & ~x["signal_climax"].fillna(False).astype(bool)
    if variant == "H16_VWAP_RECLAIM":
        return h18 & x["low_open"].fillna(False) & x["had_below_vwap_before_1445"].fillna(False) & x["reclaim_by_1445"].fillna(False)
    if variant == "H16_PREVCLOSE_RECLAIM":
        return h18 & x["low_open"].fillna(False) & x["reclaim_prevclose_1445"].fillna(False)
    if variant == "H17_FIRST_RECLAIM":
        return h18 & x["had_below_vwap_before_1445"].fillna(False) & x["reclaim_by_1445"].fillna(False) & x["below_vwap_episode_count"].eq(1)
    if variant == "H03_H17_FIRST_RECLAIM":
        return (
            h18
            & ~x["signal_climax"].fillna(False).astype(bool)
            & x["had_below_vwap_before_1445"].fillna(False)
            & x["reclaim_by_1445"].fillna(False)
            & x["below_vwap_episode_count"].eq(1)
        )
    raise ValueError(variant)


def _select(x: pd.DataFrame, variant: str, entry_time: str) -> pd.DataFrame:
    col = _entry_col(entry_time)
    y = x[_book_mask(x, variant)].copy()
    y = y[y[col].notna() & y["exit_1000"].notna() & y["upper_limit"].notna()].copy()
    y["limit_gap"] = y["upper_limit"] / y[col] - 1.0
    # H18: no at/near limit chase at actual delayed entry time.
    y = y[y["limit_gap"].ge(LIMIT_BUFFER)].copy()
    y["score"] = y["clean_mom20_rank"].fillna(-np.inf)
    z = y.sort_values(["trade_date", "score", "instrument"], ascending=[True, False, True]).copy()
    z["rank"] = z.groupby("trade_date").cumcount() + 1
    counts = z.groupby("trade_date")["instrument"].transform("size")
    return z[(z["rank"] <= TOP_N) & (counts >= TOP_N)].copy()


def _portfolio_series(selected: pd.DataFrame, all_dates: list[pd.Timestamp], entry_time: str, cost: str) -> tuple[pd.Series, pd.DataFrame]:
    entry_col = _entry_col(entry_time)
    z = selected.copy()
    idx = pd.DatetimeIndex(all_dates)
    if z.empty:
        return pd.Series(0.0, index=idx), z
    z["net_return"] = v43._net_return(z[entry_col], z["exit_1000"], z["trade_date"], cost)
    daily = z.groupby("trade_date")["net_return"].mean()
    return daily.reindex(idx, fill_value=0.0), z


def _period_metrics(series: pd.Series, ledger: pd.DataFrame) -> dict[str, Any]:
    all_s, all_l = v43._slice(series, ledger, None, None)
    p1_s, p1_l = v43._slice(series, ledger, None, pd.Timestamp("2023-12-31"))
    p2_s, p2_l = v43._slice(series, ledger, pd.Timestamp("2024-01-01"), None)
    return {
        "all": v43._metrics(all_s, all_l),
        "2021_2023": v43._metrics(p1_s, p1_l),
        "2024_2026": v43._metrics(p2_s, p2_l),
    }


def _flat(results: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in results:
        for period, m in item["metrics"].items():
            rows.append({
                "variant": item["variant"],
                "book_hypotheses": "+".join(item["book_hypotheses"]),
                "entry_time": item["entry_time"],
                "cost": item["cost"],
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


def _variant_ids(name: str) -> list[str]:
    if name == "BASELINE_H18": return ["H18"]
    if name == "H03_VETO": return ["H03", "H18"]
    if name.startswith("H16_"): return ["H16", "H18"]
    if name == "H17_FIRST_RECLAIM": return ["H17", "H18"]
    if name == "H03_H17_FIRST_RECLAIM": return ["H03", "H17", "H18"]
    raise ValueError(name)


def run() -> dict[str, Any]:
    candidates, all_dates = _prepare_candidates()
    minute = _load_minute_path(candidates)
    features = _path_features(candidates, minute)
    results: list[dict[str, Any]] = []
    ledgers: list[pd.DataFrame] = []

    for variant in VARIANTS:
        for entry_time in ENTRY_TIMES:
            selected = _select(features, variant, entry_time)
            for cost in COSTS:
                series, ledger = _portfolio_series(selected, all_dates, entry_time, cost)
                item = {
                    "variant": variant,
                    "book_hypotheses": _variant_ids(variant),
                    "entry_time": entry_time,
                    "cost": cost,
                    "metrics": _period_metrics(series, ledger),
                }
                results.append(item)
                if cost == "BASE" and not ledger.empty:
                    l = ledger.copy()
                    l["variant"] = variant
                    l["entry_time"] = entry_time
                    l["book_hypotheses"] = "+".join(_variant_ids(variant))
                    ledgers.append(l)

    report = {
        "status": "EXPLORATORY_CAUSAL_BOOK_ANCHORED_NOT_PRISTINE_OOS",
        "source_policy": "Every strategy overlay must map to BOOK_ALPHA_HYPOTHESIS_REGISTRY.md; generic factors are not allowed to invent a strategy rule here.",
        "candidate_core_provenance": "LIMIT_ADJUSTED_MOMENTUM is external_A_share_evidence_challenger, retained only as validated candidate core and not attributed to any trader.",
        "book_source_trace": BOOK_SOURCE,
        "preregistration": {
            "fixed_context": "X02 candidate core + T-1 breadth5>0 + money_effect>0 + Top3 + T+1 10:00 exit",
            "variants": list(VARIANTS),
            "entry_times": list(ENTRY_TIMES),
            "delay_test": "same information frozen at 14:45; 14:50/14:55 only stress execution delay",
            "h18_limit_buffer": LIMIT_BUFFER,
            "rank": "clean_mom20_rank only; book modules are trigger/veto, not optimized weights",
            "no_best_variant_selection": True,
        },
        "coverage": {
            "candidate_rows": int(len(candidates)),
            "candidate_dates": int(candidates["trade_date"].nunique()),
            "minute_rows": int(len(minute)),
            "feature_rows": int(len(features)),
            "feature_dates": int(features["trade_date"].nunique()) if not features.empty else 0,
        },
        "results": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _flat(results).to_csv(CSV_OUTPUT, index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(LEDGER_OUTPUT, index=False)
    print(json.dumps({
        "status": report["status"],
        "coverage": report["coverage"],
        "base_results": [x for x in results if x["cost"] == "BASE"],
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
