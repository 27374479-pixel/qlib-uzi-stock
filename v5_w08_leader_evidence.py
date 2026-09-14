from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from daily_event_role_backtest import Config as EventConfig, load_panel
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "V5_W08_LEADER_EVIDENCE_SPEC.md"
OUT = ROOT / "output" / "v5_w08_leader_evidence"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "leader_evidence.parquet"
START = "2021-05-17"
END = "2026-09-03"

CONTRACT = {
    "version": "V5_W08_LEADER_EVIDENCE_V1",
    "mode": "STRUCTURAL_REPRESENTATION_ONLY",
    "uses_strategy_returns": False,
    "parameter_search": False,
    "leader_score_authorized": False,
    "leader_rank_authorized": False,
    "leader_label_authorized": False,
    "top_anchor_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}

REQUIRED = {
    "instrument", "date", "preclose", "amount", "turnover_rate_pct",
    "seal_up", "one_word", "board_height",
}


def build_leader_evidence(panel: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(REQUIRED - set(panel.columns))
    if missing:
        raise RuntimeError(f"W08 panel missing fields: {missing}")

    x = panel.copy()
    x["date"] = pd.to_datetime(x["date"], errors="coerce").dt.normalize()
    if x["date"].isna().any():
        raise RuntimeError("W08 invalid dates")
    if x[["instrument", "date"]].duplicated().any():
        raise RuntimeError("W08 duplicate instrument/date rows")
    x = x.sort_values(["instrument", "date"]).reset_index(drop=True)
    x["board_height"] = pd.to_numeric(x["board_height"], errors="coerce").fillna(0).astype(int)
    x["preclose"] = pd.to_numeric(x["preclose"], errors="coerce")
    x["amount"] = pd.to_numeric(x["amount"], errors="coerce")
    x["turnover_rate_pct"] = pd.to_numeric(x["turnover_rate_pct"], errors="coerce")
    x["seal_up"] = x["seal_up"].fillna(False).astype(bool)
    x["one_word"] = x["one_word"].fillna(False).astype(bool)

    x["prior_board_height"] = x.groupby("instrument", sort=False)["board_height"].shift(1).fillna(0).astype(int)
    x["three_plus_board"] = x["board_height"].ge(3)
    x["accessible_board_proxy"] = x["seal_up"] & ~x["one_word"]
    x["first_unsealed_after_3plus_proxy"] = ~x["seal_up"] & x["prior_board_height"].ge(3)

    complete = pd.Series(False, index=x.index, dtype=bool)
    launch = pd.Series(np.nan, index=x.index, dtype=float)
    all_access = pd.Series(pd.NA, index=x.index, dtype="boolean")

    for _, idx in x.groupby("instrument", sort=False).groups.items():
        known = False
        launch_price = np.nan
        all_accessible = True
        previous_height = 0
        for i in idx:
            height = int(x.at[i, "board_height"])
            sealed = bool(x.at[i, "seal_up"])
            if not sealed or height <= 0:
                known = False
                launch_price = np.nan
                all_accessible = True
                previous_height = 0
                continue
            if height == 1:
                known = bool(np.isfinite(x.at[i, "preclose"]) and x.at[i, "preclose"] > 0)
                launch_price = float(x.at[i, "preclose"]) if known else np.nan
                all_accessible = bool(x.at[i, "accessible_board_proxy"])
            elif known and previous_height == height - 1:
                all_accessible = all_accessible and bool(x.at[i, "accessible_board_proxy"])
            else:
                known = False
                launch_price = np.nan
                all_accessible = True
            complete.at[i] = known
            if known:
                launch.at[i] = launch_price
                all_access.at[i] = all_accessible
            previous_height = height

    x["streak_history_complete"] = complete
    x["streak_launch_price"] = launch
    x["streak_all_accessible_proxy"] = all_access
    x["launch_price_lt_10"] = pd.Series(pd.NA, index=x.index, dtype="boolean")
    known_launch = x["streak_launch_price"].notna()
    x.loc[known_launch, "launch_price_lt_10"] = x.loc[known_launch, "streak_launch_price"].lt(10.0)
    x["amount_ge_1bn"] = pd.Series(pd.NA, index=x.index, dtype="boolean")
    known_amount = np.isfinite(x["amount"].to_numpy(float))
    x.loc[known_amount, "amount_ge_1bn"] = x.loc[known_amount, "amount"].ge(1_000_000_000.0)

    keep = x["seal_up"] | x["first_unsealed_after_3plus_proxy"]
    columns = [
        "instrument", "date", "board_height", "three_plus_board", "one_word",
        "accessible_board_proxy", "streak_history_complete", "streak_all_accessible_proxy",
        "streak_launch_price", "launch_price_lt_10", "first_unsealed_after_3plus_proxy",
        "amount", "turnover_rate_pct", "amount_ge_1bn",
    ]
    return x.loc[keep, columns].reset_index(drop=True)


def invariant_failures(frame: pd.DataFrame) -> dict[str, int]:
    failures = {
        "duplicate_instrument_date": int(frame[["instrument", "date"]].duplicated().sum()),
        "three_plus_mismatch": int((frame["three_plus_board"] != frame["board_height"].ge(3)).sum()),
        "accessible_proxy_mismatch": int((frame["accessible_board_proxy"] != (~frame["one_word"])).sum()),
        "incomplete_streak_has_launch": int((~frame["streak_history_complete"] & frame["streak_launch_price"].notna()).sum()),
        "incomplete_streak_has_access_verdict": int((~frame["streak_history_complete"] & frame["streak_all_accessible_proxy"].notna()).sum()),
        "launch_flag_mismatch": 0,
        "amount_flag_mismatch": 0,
    }
    known_launch = frame["streak_launch_price"].notna()
    failures["launch_flag_mismatch"] = int(
        (frame.loc[known_launch, "launch_price_lt_10"].astype(bool).to_numpy()
         != frame.loc[known_launch, "streak_launch_price"].lt(10.0).to_numpy()).sum()
    )
    known_amount = frame["amount"].notna() & np.isfinite(frame["amount"].to_numpy(float))
    failures["amount_flag_mismatch"] = int(
        (frame.loc[known_amount, "amount_ge_1bn"].astype(bool).to_numpy()
         != frame.loc[known_amount, "amount"].ge(1_000_000_000.0).to_numpy()).sum()
    )
    return failures


def run() -> dict:
    if not SPEC.exists():
        raise FileNotFoundError(SPEC)
    panel, metadata = load_panel(EventConfig(universe="csi800", start=START, end=END))
    frame = build_leader_evidence(panel)
    failures = invariant_failures(frame)
    valid = not any(failures.values())
    status = "STRUCTURALLY_VALID_FOR_DESCRIPTIVE_LEADER_EVIDENCE" if valid else "TECHNICALLY_INVALID"
    OUT.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OBSERVATIONS, index=False, compression="zstd")
    report = {
        "contract": CONTRACT,
        "spec_sha256": sha256_file(SPEC),
        "status": status,
        "panel_metadata": metadata,
        "period": {"start": START, "end": END, "evidence_rows": int(len(frame)), "instruments": int(frame["instrument"].nunique())},
        "coverage": {
            "sealed_rows": int(frame["board_height"].gt(0).sum()),
            "three_plus_rows": int(frame["three_plus_board"].sum()),
            "complete_streak_rows": int(frame["streak_history_complete"].sum()),
            "all_accessible_known_true": int(frame["streak_all_accessible_proxy"].fillna(False).sum()),
            "first_unsealed_after_3plus_proxy_rows": int(frame["first_unsealed_after_3plus_proxy"].sum()),
            "amount_ge_1bn_rows": int(frame["amount_ge_1bn"].fillna(False).sum()),
            "launch_price_lt_10_rows": int(frame["launch_price_lt_10"].fillna(False).sum()),
        },
        "invariant_failures": failures,
        "unresolved_source_traits": [
            "sustained large-theme / strong-theme logic",
            "continued news/message fermentation",
            "exact historical-high disagreement amount history scope",
            "end of index adjustment / early start relative to it",
            "exact turnover semantics of board-by-board accessibility",
            "market-total-leader identity among multiple candidates",
        ],
        "authorizations": {
            "descriptive_representation": valid,
            "leader_score": False,
            "leader_rank": False,
            "leader_label": False,
            "top_anchor": False,
            "w01_return_screen": False,
            "x02_change": False,
            "portfolio_combination": False,
            "paper_trading": False,
            "live_trading": False,
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": status, "period": report["period"], "coverage": report["coverage"], "invariant_failures": failures}, ensure_ascii=False, indent=2))
    if not valid:
        raise SystemExit(2)
    return report


if __name__ == "__main__":
    run()
