"""L01 structural audit for book-named leader stages.

This module intentionally does not evaluate returns.  It translates the
book-named sequence (launch -> confirmation -> fermentation -> acceleration ->
disagreement -> counter-wrap -> dragon-return) into a frozen, transparent
point-in-time daily proxy and audits only representation/transition structure.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from attention_timing_decomposition import Config as TimingConfig, prepare as prepare_timing
import v5_b01_leader_disagreement_screen as b01
from x02_provenance import sha256_file

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "V5_L01_LEADER_STAGE_PROXY_SPEC.md"
OUT = ROOT / "output" / "v5_l01_leader_stage_transition"
REPORT = OUT / "report.json"
OBSERVATIONS = OUT / "stage_observations.parquet"
START = pd.Timestamp("2021-05-17")

STAGES = (
    "launch",
    "confirmation",
    "fermentation",
    "acceleration",
    "disagreement",
    "counter_wrap",
    "dragon_return",
)
RAW_FLAG_COLUMNS = tuple(f"raw_{name}" for name in STAGES)

CONTRACT = {
    "version": "V5_L01_LEADER_STAGE_PROXY_V1",
    "source": "user-supplied lower 48-trader volume, PDF page 123/227 (printed p.92)",
    "source_sequence": list(STAGES),
    "source_sequence_cn": ["启动", "确认", "发酵", "加速", "分歧", "反包", "龙回头"],
    "proxy": {
        "launch": "seal_up and board_height == 1",
        "confirmation": "seal_up and board_height == 2",
        "fermentation": "seal_up and board_height == 3",
        "acceleration": "seal_up and board_height >= 4",
        "disagreement": "not seal_up; T-1 sealed with board_height >= 3",
        "counter_wrap": "seal_up; T-1 not sealed; T-2 sealed with board_height >= 3",
        "dragon_return": (
            "seal_up after exactly 2 or 3 consecutive non-sealed rows; "
            "preceding row before interruption sealed with board_height >= 3"
        ),
    },
    "label_precedence": [
        "dragon_return",
        "counter_wrap",
        "disagreement",
        "acceleration",
        "fermentation",
        "confirmation",
        "launch",
    ],
    "uses_forward_returns": False,
    "parameter_search": False,
    "alpha_evaluation_authorized": False,
    "trading_signal_authorized": False,
    "portfolio_combination_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def annotate_stages(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"instrument", "date", "seal_up", "board_height"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"L01 frame missing required fields: {missing}")

    x = frame.copy()
    x["date"] = pd.to_datetime(x["date"], errors="coerce")
    if x["date"].isna().any():
        raise RuntimeError("L01 frame contains invalid dates")
    if x[["instrument", "date"]].duplicated().any():
        dup = int(x[["instrument", "date"]].duplicated(keep=False).sum())
        raise RuntimeError(f"L01 frame contains duplicate instrument/date rows: {dup}")

    x = x.sort_values(["instrument", "date"]).reset_index(drop=True)
    x["row_in_instrument"] = x.groupby("instrument", sort=False).cumcount()
    x["seal_bool"] = x["seal_up"].fillna(False).astype(bool)
    x["board_num"] = _num(x["board_height"])
    g = x.groupby("instrument", sort=False)
    for lag in range(1, 5):
        x[f"seal_lag{lag}"] = g["seal_bool"].shift(lag).fillna(False).astype(bool)
        x[f"board_lag{lag}"] = _num(g["board_num"].shift(lag))

    seal = x["seal_bool"]
    board = x["board_num"]
    x["raw_launch"] = seal & board.eq(1)
    x["raw_confirmation"] = seal & board.eq(2)
    x["raw_fermentation"] = seal & board.eq(3)
    x["raw_acceleration"] = seal & board.ge(4)
    x["raw_disagreement"] = ~seal & x["seal_lag1"] & x["board_lag1"].ge(3)
    x["raw_counter_wrap"] = seal & ~x["seal_lag1"] & x["seal_lag2"] & x["board_lag2"].ge(3)

    gap2 = seal & ~x["seal_lag1"] & ~x["seal_lag2"] & x["seal_lag3"] & x["board_lag3"].ge(3)
    gap3 = (
        seal
        & ~x["seal_lag1"]
        & ~x["seal_lag2"]
        & ~x["seal_lag3"]
        & x["seal_lag4"]
        & x["board_lag4"].ge(3)
    )
    x["raw_dragon_return"] = gap2 | gap3
    x["dragon_return_gap_sessions"] = np.select([gap2, gap3], [2, 3], default=0).astype(int)

    precedence = CONTRACT["label_precedence"]
    x["stage_proxy"] = np.select(
        [x[f"raw_{name}"] for name in precedence],
        precedence,
        default="unlabelled",
    )
    return x


def _stage_counts(x: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for stage in STAGES:
        s = x.loc[x["stage_proxy"].eq(stage)]
        out[stage] = {
            "rows": int(len(s)),
            "active_dates": int(s["date"].nunique()),
            "instruments": int(s["instrument"].nunique()),
        }
    out["unlabelled"] = {
        "rows": int(x["stage_proxy"].eq("unlabelled").sum()),
        "active_dates": int(x.loc[x["stage_proxy"].eq("unlabelled"), "date"].nunique()),
        "instruments": int(x.loc[x["stage_proxy"].eq("unlabelled"), "instrument"].nunique()),
    }
    return out


def _raw_overlap(x: pd.DataFrame) -> dict[str, Any]:
    flags = x[list(RAW_FLAG_COLUMNS)].astype(int)
    multiplicity = flags.sum(axis=1)
    pairs: list[dict[str, Any]] = []
    for i, left in enumerate(STAGES):
        for right in STAGES[i + 1 :]:
            n = int((x[f"raw_{left}"] & x[f"raw_{right}"]).sum())
            if n:
                pairs.append({"left": left, "right": right, "rows": n})
    return {
        "rows_with_multiple_raw_flags": int(multiplicity.gt(1).sum()),
        "maximum_raw_flags_on_one_row": int(multiplicity.max()) if len(multiplicity) else 0,
        "overlap_pairs": pairs,
        "note": "Raw overlap is allowed because recovery labels intentionally override ordinary board-height labels.",
    }


def _transition_records(x: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    ordered = x.sort_values(["instrument", "date"]).copy()
    g = ordered.groupby("instrument", sort=False)
    ordered["next_row_stage"] = g["stage_proxy"].shift(-1)

    immediate = (
        ordered.loc[ordered["stage_proxy"].ne("unlabelled") & ordered["next_row_stage"].notna()]
        .groupby(["stage_proxy", "next_row_stage"], sort=True)
        .size()
        .rename("rows")
        .reset_index()
        .rename(columns={"stage_proxy": "from_stage", "next_row_stage": "to_stage"})
    )

    labelled = ordered.loc[ordered["stage_proxy"].ne("unlabelled")].copy()
    lg = labelled.groupby("instrument", sort=False)
    labelled["next_labeled_stage"] = lg["stage_proxy"].shift(-1)
    labelled["next_labeled_row"] = lg["row_in_instrument"].shift(-1)
    labelled["rows_until_next_labeled"] = labelled["next_labeled_row"] - labelled["row_in_instrument"]
    next_labelled = (
        labelled.loc[labelled["next_labeled_stage"].notna()]
        .groupby(["stage_proxy", "next_labeled_stage"], sort=True)
        .agg(rows=("stage_proxy", "size"), median_rows_until_next=("rows_until_next_labeled", "median"))
        .reset_index()
        .rename(columns={"stage_proxy": "from_stage", "next_labeled_stage": "to_stage"})
    )

    return {
        "immediate_next_row": immediate.to_dict(orient="records"),
        "next_labelled_stage": next_labelled.to_dict(orient="records"),
    }


def _rate(mask: pd.Series, condition: pd.Series) -> dict[str, Any]:
    total = int(mask.sum())
    matched = int((mask & condition.fillna(False)).sum())
    return {
        "matched": matched,
        "total": total,
        "rate": float(matched / total) if total else None,
    }


def precursor_consistency(x: pd.DataFrame) -> dict[str, Any]:
    ordered = x.sort_values(["instrument", "date"]).copy()
    g = ordered.groupby("instrument", sort=False)
    prev_stage = g["stage_proxy"].shift(1)

    confirmation = ordered["stage_proxy"].eq("confirmation")
    fermentation = ordered["stage_proxy"].eq("fermentation")
    first_acceleration = ordered["stage_proxy"].eq("acceleration") & ordered["board_num"].eq(4)
    later_acceleration = ordered["stage_proxy"].eq("acceleration") & ordered["board_num"].gt(4)
    disagreement = ordered["stage_proxy"].eq("disagreement")
    counter_wrap = ordered["stage_proxy"].eq("counter_wrap")
    dragon_return = ordered["stage_proxy"].eq("dragon_return")

    return {
        "confirmation_immediately_after_launch": _rate(confirmation, prev_stage.eq("launch")),
        "fermentation_immediately_after_confirmation": _rate(fermentation, prev_stage.eq("confirmation")),
        "first_acceleration_immediately_after_fermentation": _rate(first_acceleration, prev_stage.eq("fermentation")),
        "later_acceleration_immediately_after_acceleration": _rate(later_acceleration, prev_stage.eq("acceleration")),
        "disagreement_immediately_after_high_board_stage": _rate(
            disagreement, prev_stage.isin(["fermentation", "acceleration"])
        ),
        "counter_wrap_immediately_after_disagreement": _rate(counter_wrap, prev_stage.eq("disagreement")),
        "dragon_return_has_frozen_2_or_3_session_gap": _rate(
            dragon_return, ordered["dragon_return_gap_sessions"].isin([2, 3])
        ),
    }


def invariant_failures(x: pd.DataFrame) -> dict[str, int]:
    seal = x["seal_bool"]
    board = x["board_num"]
    expected = {
        "launch": seal & board.eq(1),
        "confirmation": seal & board.eq(2),
        "fermentation": seal & board.eq(3),
        "acceleration": seal & board.ge(4),
        "disagreement": ~seal & x["seal_lag1"] & x["board_lag1"].ge(3),
        "counter_wrap": seal & ~x["seal_lag1"] & x["seal_lag2"] & x["board_lag2"].ge(3),
        "dragon_return": x["raw_dragon_return"],
    }
    failures = {
        stage: int((x["stage_proxy"].eq(stage) & ~condition.fillna(False)).sum())
        for stage, condition in expected.items()
    }
    failures["dragon_return_precedence"] = int(
        (x["raw_dragon_return"] & ~x["stage_proxy"].eq("dragon_return")).sum()
    )
    failures["counter_wrap_precedence"] = int(
        (
            x["raw_counter_wrap"]
            & ~x["raw_dragon_return"]
            & ~x["stage_proxy"].eq("counter_wrap")
        ).sum()
    )
    return failures


def prepare_frame() -> pd.DataFrame:
    config = b01.screen_config()
    timing = TimingConfig(
        universe=config.universe,
        start=config.start,
        end=config.end,
        oos_start=config.oos_start,
        round_trip_cost=config.round_trip_cost,
        bootstrap_samples=config.bootstrap_samples,
        seed=config.seed,
    )
    frame = prepare_timing(timing)
    dates = pd.to_datetime(frame["date"], errors="coerce")
    return frame.loc[dates.ge(START)].copy()


def run() -> dict[str, Any]:
    if not SPEC.exists():
        raise FileNotFoundError(SPEC)

    frame = prepare_frame()
    annotated = annotate_stages(frame)
    failures = invariant_failures(annotated)
    structurally_valid = not any(failures.values())
    status = (
        "STRUCTURALLY_VALID_FOR_DESCRIPTIVE_STAGE_AUDIT"
        if structurally_valid
        else "TECHNICALLY_INVALID"
    )

    OUT.mkdir(parents=True, exist_ok=True)
    keep = [
        "date",
        "instrument",
        "seal_bool",
        "board_num",
        "stage_proxy",
        "dragon_return_gap_sessions",
        *RAW_FLAG_COLUMNS,
    ]
    observations = annotated.loc[annotated["stage_proxy"].ne("unlabelled"), keep].copy()
    observations.to_parquet(OBSERVATIONS, index=False, compression="zstd")

    report = {
        "contract": CONTRACT,
        "spec_sha256": sha256_file(SPEC),
        "status": status,
        "period": {
            "start": str(annotated["date"].min().date()) if len(annotated) else None,
            "end": str(annotated["date"].max().date()) if len(annotated) else None,
        },
        "rows": {
            "all": int(len(annotated)),
            "labelled": int(annotated["stage_proxy"].ne("unlabelled").sum()),
            "instruments": int(annotated["instrument"].nunique()),
            "active_dates": int(annotated["date"].nunique()),
        },
        "stage_counts": _stage_counts(annotated),
        "raw_overlap": _raw_overlap(annotated),
        "invariant_failures": failures,
        "precursor_consistency": precursor_consistency(annotated),
        "transitions": _transition_records(annotated),
        "interpretation_boundary": (
            "Structural representation only. No forward returns are evaluated and no stage is a trading signal. "
            "A later economic test requires a separate preregistration before outcomes are read."
        ),
        "authorizations": {
            "alpha_evaluation": False,
            "trading_signal": False,
            "portfolio_combination": False,
            "paper_trading": False,
            "live_trading": False,
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": status,
                "rows": report["rows"],
                "stage_counts": report["stage_counts"],
                "invariant_failures": failures,
                "precursor_consistency": report["precursor_consistency"],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return report


if __name__ == "__main__":
    run()
