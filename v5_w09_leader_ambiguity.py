"""W09 descriptive ambiguity audit over frozen W08 leader evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from daily_event_role_backtest import Config as EventConfig, load_panel
from v5_w08_leader_evidence import build_leader_evidence
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "V5_W09_LEADER_AMBIGUITY_SPEC.md"
W08_RESULT = ROOT / "V5_W08_RESULT.md"
OUT = ROOT / "output" / "v5_w09_leader_ambiguity"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "leader_ambiguity.parquet"
START = "2021-05-17"
END = "2026-09-03"

COUNT_COLUMNS = (
    "sealed_evidence_n",
    "max_board_height",
    "max_board_candidate_n",
    "three_plus_candidate_n",
    "complete_three_plus_candidate_n",
    "accessible_three_plus_candidate_n",
    "launch_lt10_three_plus_known_n",
    "launch_lt10_three_plus_true_n",
    "first_unsealed_after_3plus_n",
)

CONTRACT = {
    "version": "V5_W09_LEADER_AMBIGUITY_V1",
    "mode": "STRUCTURAL_REPRESENTATION_ONLY",
    "market_max_board_is_leader_definition": False,
    "uses_strategy_returns": False,
    "parameter_search": False,
    "leader_score_authorized": False,
    "leader_rank_authorized": False,
    "leader_label_authorized": False,
    "tie_resolution_authorized": False,
    "w01_return_screen_authorized": False,
    "x02_change_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def build_leader_ambiguity(evidence: pd.DataFrame, all_dates: Iterable | None = None) -> pd.DataFrame:
    required = {
        "date", "board_height", "three_plus_board", "streak_history_complete",
        "streak_all_accessible_proxy", "launch_price_lt_10",
        "first_unsealed_after_3plus_proxy",
    }
    missing = sorted(required - set(evidence.columns))
    if missing:
        raise RuntimeError(f"W09 W08 evidence missing fields: {missing}")

    x = evidence.copy()
    x["date"] = pd.to_datetime(x["date"], errors="coerce").dt.normalize()
    if x["date"].isna().any():
        raise RuntimeError("W09 evidence contains invalid dates")
    x["board_height"] = pd.to_numeric(x["board_height"], errors="coerce").fillna(0).astype(int)
    x["three_plus_board"] = x["three_plus_board"].fillna(False).astype(bool)
    x["streak_history_complete"] = x["streak_history_complete"].fillna(False).astype(bool)
    x["first_unsealed_after_3plus_proxy"] = x["first_unsealed_after_3plus_proxy"].fillna(False).astype(bool)

    if all_dates is None:
        dates = pd.Index(sorted(x["date"].unique()))
    else:
        dates = pd.Index(pd.to_datetime(list(all_dates), errors="coerce")).dropna().normalize().unique().sort_values()

    rows = []
    for date in dates:
        day = x.loc[x["date"].eq(date)].copy()
        sealed = day.loc[day["board_height"].gt(0)]
        max_height = int(sealed["board_height"].max()) if len(sealed) else 0
        max_n = int(sealed["board_height"].eq(max_height).sum()) if max_height > 0 else 0
        three = sealed.loc[sealed["three_plus_board"]]
        complete = three.loc[three["streak_history_complete"]]
        accessible_true = complete["streak_all_accessible_proxy"].fillna(False).astype(bool)
        launch_known = three["launch_price_lt_10"].notna()
        launch_true = three["launch_price_lt_10"].fillna(False).astype(bool)
        first_unsealed_n = int(day["first_unsealed_after_3plus_proxy"].sum())
        rows.append({
            "date": date,
            "sealed_evidence_n": int(len(sealed)),
            "max_board_height": max_height,
            "max_board_candidate_n": max_n,
            "three_plus_candidate_n": int(len(three)),
            "complete_three_plus_candidate_n": int(len(complete)),
            "accessible_three_plus_candidate_n": int(accessible_true.sum()),
            "launch_lt10_three_plus_known_n": int(launch_known.sum()),
            "launch_lt10_three_plus_true_n": int(launch_true.sum()),
            "first_unsealed_after_3plus_n": first_unsealed_n,
            "max_board_tie": bool(max_n > 1),
            "three_plus_multiplicity": bool(len(three) > 1),
        })
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def invariant_failures(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty:
        return {"empty": 1}
    counts = frame[list(COUNT_COLUMNS)]
    return {
        "duplicate_dates": int(frame["date"].duplicated().sum()),
        "negative_counts": int((counts < 0).sum().sum()),
        "max_candidates_exceed_sealed": int((frame["max_board_candidate_n"] > frame["sealed_evidence_n"]).sum()),
        "three_plus_exceed_sealed": int((frame["three_plus_candidate_n"] > frame["sealed_evidence_n"]).sum()),
        "complete_exceed_three_plus": int((frame["complete_three_plus_candidate_n"] > frame["three_plus_candidate_n"]).sum()),
        "accessible_exceed_complete": int((frame["accessible_three_plus_candidate_n"] > frame["complete_three_plus_candidate_n"]).sum()),
        "launch_known_exceed_three_plus": int((frame["launch_lt10_three_plus_known_n"] > frame["three_plus_candidate_n"]).sum()),
        "launch_true_exceed_known": int((frame["launch_lt10_three_plus_true_n"] > frame["launch_lt10_three_plus_known_n"]).sum()),
        "max_tie_mismatch": int((frame["max_board_tie"] != frame["max_board_candidate_n"].gt(1)).sum()),
        "three_plus_multiplicity_mismatch": int((frame["three_plus_multiplicity"] != frame["three_plus_candidate_n"].gt(1)).sum()),
        "zero_sealed_has_nonzero_max": int(((frame["sealed_evidence_n"] == 0) & ((frame["max_board_height"] != 0) | (frame["max_board_candidate_n"] != 0))).sum()),
    }


def run() -> dict:
    for path in (SPEC, W08_RESULT):
        if not path.exists():
            raise FileNotFoundError(path)
    panel, metadata = load_panel(EventConfig(universe="csi800", start=START, end=END))
    evidence = build_leader_evidence(panel)
    dates = pd.to_datetime(panel["date"], errors="coerce").dropna().dt.normalize().unique()
    frame = build_leader_ambiguity(evidence, dates)
    failures = invariant_failures(frame)
    valid = not any(failures.values())
    status = "STRUCTURALLY_VALID_FOR_DESCRIPTIVE_LEADER_AMBIGUITY" if valid else "TECHNICALLY_INVALID"

    OUT.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OBSERVATIONS, index=False, compression="zstd")
    report = {
        "contract": CONTRACT,
        "lineage": {"spec_sha256": sha256_file(SPEC), "w08_result_sha256": sha256_file(W08_RESULT)},
        "status": status,
        "panel_metadata": metadata,
        "period": {"start": str(frame["date"].min().date()), "end": str(frame["date"].max().date()), "dates": int(len(frame))},
        "invariant_failures": failures,
        "descriptive_ambiguity": {
            "dates_with_sealed_evidence": int(frame["sealed_evidence_n"].gt(0).sum()),
            "dates_with_three_plus_candidate": int(frame["three_plus_candidate_n"].gt(0).sum()),
            "dates_with_multiple_three_plus_candidates": int(frame["three_plus_multiplicity"].sum()),
            "dates_with_max_board_tie": int(frame["max_board_tie"].sum()),
            "dates_with_first_unsealed_after_3plus": int(frame["first_unsealed_after_3plus_n"].gt(0).sum()),
        },
        "authorizations": {
            "descriptive_representation": valid,
            "leader_score": False,
            "leader_rank": False,
            "leader_label": False,
            "tie_resolution": False,
            "w01_return_screen": False,
            "x02_change": False,
            "portfolio_combination": False,
            "paper_trading": False,
            "live_trading": False,
        },
        "interpretation_boundary": "W09 quantifies candidate multiplicity only. Market-maximum board height is a descriptive lens, not a leader definition, and observed frequencies may not be used to choose a leader rule from W01 returns.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": status, "period": report["period"], "invariant_failures": failures, "descriptive_ambiguity": report["descriptive_ambiguity"]}, ensure_ascii=False, indent=2))
    if not valid:
        raise SystemExit(2)
    return report


if __name__ == "__main__":
    run()
