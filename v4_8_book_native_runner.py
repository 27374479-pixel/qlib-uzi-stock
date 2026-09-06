"""Runner for V4.8 using a transparent book-derived H07 core proxy.

Positive candidate eligibility deliberately avoids the hand-weighted role_score:
- historical activity already exists (prior touch/seal evidence);
- current T-1 return remains in the top 25% of its point-in-time industry/theme proxy;
- not a one-word locked board.

This mirrors BOOK_ALPHA_HYPOTHESIS_REGISTRY H07's 'existing survivor/core'
concept more directly than the legacy weighted role_score. H03 climax remains
only a veto experiment.
"""
from __future__ import annotations

import json
import pandas as pd

import v4_8_book_native_reclaim_validation as m


def _daily_context_book_core():
    cfg = m.base.Config(start="2015-01-01", end="2026-09-03")
    frame = m.survivor.prepare(cfg).copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    nxt = m._next_map(frame)

    prior_touch = pd.to_numeric(frame["prior_touch20"], errors="coerce").fillna(0) if "prior_touch20" in frame else pd.Series(0.0, index=frame.index)
    prior_seal = pd.to_numeric(frame["prior_seal5"], errors="coerce").fillna(0) if "prior_seal5" in frame else pd.Series(0.0, index=frame.index)
    prior_active = prior_touch.gt(0) | prior_seal.gt(0)
    ret_rank = pd.to_numeric(frame["ret_rank"], errors="coerce") if "ret_rank" in frame else pd.Series(float("nan"), index=frame.index)
    one_word = frame["one_word"].fillna(False).astype(bool) if "one_word" in frame else pd.Series(False, index=frame.index)
    climax = frame["climax"].fillna(False).astype(bool) if "climax" in frame else pd.Series(False, index=frame.index)

    # H07-style existing survivor: historical role evidence and still top-quartile
    # within the contemporaneous industry/theme proxy. No weighted score.
    book_core = prior_active & ret_rank.ge(0.75) & ~one_word

    signal_keep = [
        "date", "instrument", "close", "industry_code", "ret_rank",
        "breadth", "breadth5", "money_effect", "weak_market",
    ]
    parts = []
    for setup in ("H16_LOW_OPEN_RECLAIM", "H17_FIRST_DIVERGENCE_RECLAIM"):
        x = frame.loc[book_core, signal_keep].copy()
        x["setup"] = setup
        x["setup_climax"] = climax.loc[x.index].to_numpy(bool)
        x = x.rename(columns={"date": "setup_date", "close": "previous_close", "industry_code": "setup_industry_code"})
        x["trade_date"] = x["setup_date"].map(nxt)
        x["exit_date"] = x["trade_date"].map(nxt)
        parts.append(x)

    cand = pd.concat(parts, ignore_index=True).dropna(subset=["trade_date", "exit_date"])
    cand["trade_date"] = pd.to_datetime(cand["trade_date"]).dt.normalize()
    cand["exit_date"] = pd.to_datetime(cand["exit_date"]).dt.normalize()
    cand = cand[cand["trade_date"] >= m.v43.SAMPLE_START].copy()
    cand = cand[~cand["instrument"].astype(str).str.upper().str.startswith("SH688")].copy()

    exec_cols = ["date", "instrument", "upper_limit", "lower_limit", "industry_code"]
    for optional in ("trade_status", "is_st"):
        if optional in frame.columns:
            exec_cols.append(optional)
    exec_ref = frame[exec_cols].copy().rename(columns={
        "date": "trade_date",
        "upper_limit": "entry_upper_limit",
        "lower_limit": "entry_lower_limit",
        "industry_code": "trade_industry_code",
    })
    exec_ref["trade_date"] = pd.to_datetime(exec_ref["trade_date"]).dt.normalize()
    exec_ref = exec_ref.drop_duplicates(["trade_date", "instrument"], keep="last")
    cand = cand.merge(exec_ref, on=["trade_date", "instrument"], how="left", validate="many_to_one")
    if "trade_status" in cand.columns:
        cand = cand[cand["trade_status"].fillna(0).eq(1)]
    if "is_st" in cand.columns:
        cand = cand[cand["is_st"].fillna(1).eq(0)]
    cand = cand.drop_duplicates(["setup", "trade_date", "instrument"]).reset_index(drop=True)

    ref = frame[["date", "instrument", "preclose", "industry_code"]].copy().rename(columns={"date": "trade_date"})
    ref["trade_date"] = pd.to_datetime(ref["trade_date"]).dt.normalize()
    ref = ref.drop_duplicates(["trade_date", "instrument"], keep="last")
    all_dates = [d for d in sorted(frame["date"].drop_duplicates()) if d >= m.v43.SAMPLE_START]
    return cand, ref, all_dates


m._daily_context = _daily_context_book_core
report = m.run()
report["research_discipline"]["candidate_core_proxy"] = (
    "H07-style: prior_touch20>0 or prior_seal5>0, plus point-in-time industry ret_rank>=0.75, non-one-word; no weighted role_score"
)
report["proxy_limitations"] = [
    "Positive candidate selection uses the transparent H07-style prior-active + top-quartile industry-return proxy, not legacy weighted role_score.",
    "H03 climax remains an engineering proxy and is tested only as a veto comparison, not a positive alpha source.",
    "CSI industry_code remains a historical theme proxy; true point-in-time concept/event membership is a later upgrade when coverage is reliable.",
    "Peer support uses relative/ordinal conditions rather than optimized return thresholds.",
]
m.OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
