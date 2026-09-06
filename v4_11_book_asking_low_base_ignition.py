"""V4.11: book-native Asking LOW_BASE_IGNITION daily screen.

Source before data:
Asking's book-derived notes explicitly describe a relatively low-position first
volume-expanded large bullish day as a typical ultra-short candidate.  This is
mechanistically different from X02, which selects already-established clean
20-day momentum.

Frozen translation (signal at completed daily close T):
LOW BASE before T:
- T-1 ret20 <= 0;
- T-1 price_to_ma20 <= 0;
- no prior limit-touch attention in prior_touch20 ("first", not repeated heat).
IGNITION on T:
- positive return;
- top quartile cross-sectional daily return (ordinal definition of "large");
- amount_accel > 1, i.e. turnover amount above its pre-existing 5d baseline.
- non-one-word.

Two controls test the words in the book rather than just absolute performance:
1) HIGH_BASE_VOLUME: same strong volume-expanded day but prior trend/base > 0;
2) LOW_BASE_NO_VOLUME: same low-base strong day but no amount expansion.

No threshold grid is searched.  Development is <=2023; 2024-2026 is historical
holdout.  The daily screen only tests information content; a survivor still
needs minute execution validation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import book_alpha_daily_screen as core
import external_challenger_daily_screen as ext
from attention_timing_decomposition import Config as TimingConfig, prepare as prepare_timing

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "v4_11_book_asking_low_base_ignition.json"
CSV_OUTPUT = ROOT / "output" / "v4_11_book_asking_low_base_ignition.csv"
SPLIT = pd.Timestamp("2024-01-01")


def _prepare() -> pd.DataFrame:
    tc = TimingConfig(
        universe="csi800",
        start="2015-01-01",
        end="2026-09-03",
        oos_start="2024-01-01",
        round_trip_cost=0.0018,
        bootstrap_samples=5000,
        seed=20260906,
    )
    frame = ext.add_challenger_features(prepare_timing(tc), tc.round_trip_cost).copy()
    frame = frame.sort_values(["instrument", "date"]).reset_index(drop=True)
    by_stock = frame.groupby("instrument", sort=False)
    frame["prev_ret20"] = by_stock["ret20"].shift(1)
    frame["prev_price_to_ma20"] = by_stock["price_to_ma20"].shift(1)
    frame["day_ret_rank"] = frame.groupby("date")["ret1"].rank(pct=True)
    return frame


def _masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    one_word = frame["one_word"].fillna(False).astype(bool)
    prior_touch = pd.to_numeric(frame["prior_touch20"], errors="coerce").fillna(0)
    low_base = (
        pd.to_numeric(frame["prev_ret20"], errors="coerce").le(0)
        & pd.to_numeric(frame["prev_price_to_ma20"], errors="coerce").le(0)
        & prior_touch.eq(0)
    )
    high_base = (
        pd.to_numeric(frame["prev_ret20"], errors="coerce").gt(0)
        & pd.to_numeric(frame["prev_price_to_ma20"], errors="coerce").gt(0)
        & prior_touch.eq(0)
    )
    strong_day = (
        pd.to_numeric(frame["ret1"], errors="coerce").gt(0)
        & pd.to_numeric(frame["day_ret_rank"], errors="coerce").ge(0.75)
    )
    volume_up = pd.to_numeric(frame["amount_accel"], errors="coerce").gt(1.0)
    volume_not_up = pd.to_numeric(frame["amount_accel"], errors="coerce").le(1.0)
    return {
        "selected": low_base & strong_day & volume_up & ~one_word,
        "control_high_base": high_base & strong_day & volume_up & ~one_word,
        "control_no_volume": low_base & strong_day & volume_not_up & ~one_word,
    }


def _screen_config() -> core.ScreenConfig:
    return core.ScreenConfig(
        universe="csi800",
        start="2015-01-01",
        end="2026-09-03",
        oos_start="2024-01-01",
        round_trip_cost=0.0018,
        bootstrap_samples=5000,
        seed=20260906,
        min_oos_observations=50,
        min_oos_days=20,
    )


def _period(frame: pd.DataFrame, before: bool) -> pd.DataFrame:
    return frame.loc[frame["date"] < SPLIT] if before else frame.loc[frame["date"] >= SPLIT]


def _overlap_diag(frame: pd.DataFrame, selected_mask: pd.Series) -> dict[str, Any]:
    x02 = ext.challenger_masks(frame)["X02_limit_adjusted_momentum"]["selected"].fillna(False)
    a = frame.loc[selected_mask, ["date", "instrument"]].drop_duplicates()
    b = frame.loc[x02, ["date", "instrument"]].drop_duplicates()
    ak = set(zip(pd.to_datetime(a["date"]), a["instrument"].astype(str)))
    bk = set(zip(pd.to_datetime(b["date"]), b["instrument"].astype(str)))
    ad = set(pd.to_datetime(a["date"]))
    bd = set(pd.to_datetime(b["date"]))
    return {
        "low_base_rows": int(len(ak)),
        "x02_rows": int(len(bk)),
        "same_stock_date_overlap": int(len(ak & bk)),
        "row_jaccard": float(len(ak & bk) / len(ak | bk)) if (ak | bk) else None,
        "low_base_active_dates": int(len(ad)),
        "x02_active_dates": int(len(bd)),
        "active_date_jaccard": float(len(ad & bd) / len(ad | bd)) if (ad | bd) else None,
        "interpretation": "Row overlap measures whether the book setup merely re-labels X02. Low overlap is desired but does not establish alpha.",
    }


def _metrics_for(sample: pd.DataFrame, cfg: core.ScreenConfig, seed_base: int) -> dict[str, Any]:
    return {
        f"{h}d": core.sample_metrics(sample, h, cfg, seed_base + h)
        for h in (1, 2, 5)
    }


def _paired_for(a: pd.DataFrame, b: pd.DataFrame, cfg: core.ScreenConfig, seed_base: int) -> dict[str, Any]:
    return {
        f"{h}d": core.paired_difference(a, b, h, 1, cfg, seed_base + h)
        for h in (1, 2, 5)
    }


def run() -> dict[str, Any]:
    frame = _prepare()
    masks = _masks(frame)
    cfg = _screen_config()

    selected = frame.loc[masks["selected"]].copy()
    controls = {
        "HIGH_BASE_VOLUME": frame.loc[masks["control_high_base"] & ~masks["selected"]].copy(),
        "LOW_BASE_NO_VOLUME": frame.loc[masks["control_no_volume"] & ~masks["selected"]].copy(),
    }

    report_periods: dict[str, Any] = {}
    flat: list[dict[str, Any]] = []
    for period_name, before in (("development_through_2023", True), ("oos_2024_2026", False)):
        s = _period(selected, before)
        period_item: dict[str, Any] = {
            "selected": _metrics_for(s, cfg, 1000 if before else 2000),
            "controls": {},
        }
        for ci, (control_name, control) in enumerate(controls.items()):
            c = _period(control, before)
            cm = _metrics_for(c, cfg, 3000 + ci * 100 if before else 4000 + ci * 100)
            paired = _paired_for(s, c, cfg, 5000 + ci * 100 if before else 6000 + ci * 100)
            period_item["controls"][control_name] = {"metrics": cm, "paired": paired}
        report_periods[period_name] = period_item

        for h in (1, 2, 5):
            sm = period_item["selected"][f"{h}d"]
            flat.append({
                "period": period_name, "group": "SELECTED_LOW_BASE_IGNITION", "horizon": h,
                "n": sm.get("n"), "active_days": sm.get("active_days"), "mean_return": sm.get("mean_return"),
                "mean_market_excess": sm.get("mean_market_excess"),
                "trim_best5_mean_market_excess": sm.get("trim_best5_mean_market_excess"),
                "positive_halfyears": sm.get("positive_halfyears"), "negative_halfyears": sm.get("negative_halfyears"),
            })
            for control_name in controls:
                pm = period_item["controls"][control_name]["paired"][f"{h}d"]
                flat.append({
                    "period": period_name, "group": f"PAIRED_VS_{control_name}", "horizon": h,
                    "paired_days": pm.get("paired_days"),
                    "selected_minus_control": pm.get("selected_minus_control"),
                    "expected_signed_difference": pm.get("expected_signed_difference"),
                })

    # Frozen promotion rule focuses on the ultra-short 1d/2d horizons rather
    # than selecting whichever of 1/2/5d looks best after the fact.
    checks = []
    for period_name in ("development_through_2023", "oos_2024_2026"):
        item = report_periods[period_name]
        for h in (1, 2):
            sm = item["selected"][f"{h}d"]
            checks.append(bool((sm.get("mean_market_excess") or -999) > 0))
            checks.append(bool((sm.get("trim_best5_mean_market_excess") or -999) >= 0))
            for control_name in controls:
                pm = item["controls"][control_name]["paired"][f"{h}d"]
                checks.append(bool((pm.get("expected_signed_difference") or -999) > 0))
                checks.append(bool((pm.get("paired_days") or 0) >= 20))

    report = {
        "question": "Does Asking's book-derived relatively-low first volume-expanded large bullish day contain incremental, weakly-X02-related forward information?",
        "source": {
            "book_reference": ".agents/skills/asking-rhythm/references/asking-rhythm-principles.md",
            "idea": "relative low position + first volume-expanded large bullish day",
            "not_claimed": "These engineering proxies are not Asking's literal private formula.",
        },
        "frozen_definition": {
            "low_base": "T-1 ret20<=0 and T-1 close<=MA20; prior_touch20==0",
            "large_bullish_day": "T ret1>0 and date cross-sectional return rank>=75%",
            "volume_confirmation": "T amount_accel>1 versus prior 5d amount baseline",
            "control_high_base": "same strong volume day, but prior ret20>0 and prior close>MA20",
            "control_no_volume": "same low-base strong day, but amount_accel<=1",
            "entry_for_labels": "next executable open; locked upper-limit next session unfilled",
            "cost": 0.0018,
            "no_threshold_grid": True,
        },
        "coverage": {
            "frame_rows": int(len(frame)),
            "selected_rows": int(len(selected)),
            "selected_dates": int(selected["date"].nunique()),
            "control_high_base_rows": int(len(controls["HIGH_BASE_VOLUME"])),
            "control_no_volume_rows": int(len(controls["LOW_BASE_NO_VOLUME"])),
        },
        "x02_independence": _overlap_diag(frame, masks["selected"]),
        "periods": report_periods,
        "decision": {
            "promote_to_minute_layer": bool(all(checks)),
            "rule": "For both development and OOS, 1d+2d selected date-neutral excess >0, trim-best5 excess >=0, and paired differential >0 vs both controls with >=20 paired days.",
        },
        "limitations": [
            "Top-quartile daily return is an ordinal engineering translation of 'large bullish day', not a book parameter.",
            "amount_accel>1 means only above the pre-existing 5d baseline; it does not optimize a volume multiple.",
            "Daily evidence is not an executable intraday entry and cannot be promoted directly to a live strategy.",
        ],
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(flat).to_csv(CSV_OUTPUT, index=False)
    print(json.dumps({
        "coverage": report["coverage"],
        "x02_independence": report["x02_independence"],
        "decision": report["decision"],
        "oos_selected": report["periods"]["oos_2024_2026"]["selected"],
    }, ensure_ascii=False, indent=2, default=str))
    return report


if __name__ == "__main__":
    run()
