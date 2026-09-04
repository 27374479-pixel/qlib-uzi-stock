"""Canonical v2 runner for ``book_alpha_daily_screen``.

v2 adds the project's frozen research-universe policy on top of the reusable v1
hypothesis/metrics functions:

* Shanghai/Shenzhen main board + ChiNext only;
* STAR excluded by prefix;
* historical ST/trading-status filtering is inherited from daily_event_role;
* at least 120 observed trading sessions since listing before a row may signal;
* observation exports have unique columns.

The extra 120-session filter is applied only after rolling features are built,
so eligible rows keep their pre-eligibility history without allowing a young
listing to become a signal.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

import book_alpha_daily_screen as core
from daily_event_role_backtest import (
    Config as EventConfig,
    add_roles,
    build_market_state,
    build_theme_state,
    load_panel,
)

ROOT = Path(__file__).resolve().parent
ScreenConfig = core.ScreenConfig


def _allowed_instrument(instrument: str) -> bool:
    code = str(instrument).upper()
    return code.startswith((
        "SH600", "SH601", "SH603", "SH605",
        "SZ000", "SZ001", "SZ002", "SZ003", "SZ300", "SZ301",
    ))


def enforce_universe_policy(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    before = len(frame)
    board_mask = frame["instrument"].astype(str).map(_allowed_instrument)
    mature_mask = pd.to_numeric(frame["history_n"], errors="coerce").ge(120)
    result = frame.loc[board_mask & mature_mask].copy()
    meta = {
        "policy": "mainboard_chinext_no_star_historical_st_removed_listing_ge120_v1",
        "rows_before_policy": int(before),
        "rows_after_policy": int(len(result)),
        "instruments_after_policy": int(result["instrument"].nunique()),
        "removed_rows": int(before - len(result)),
    }
    return result, meta


def _observation_columns(frame: pd.DataFrame) -> list[str]:
    columns = ["date", "instrument", "entry_date", "entry_filled", "close"]
    columns += [f"return_{h}d" for h in (1, 2, 5)]
    columns += [f"market_excess_{h}d" for h in (1, 2, 5)]
    return [column for column in columns if column in frame.columns]


def run(config: ScreenConfig) -> dict[str, Any]:
    event_config = EventConfig(universe=config.universe, start=config.start, end=config.end)
    panel, metadata = load_panel(event_config)
    market = build_market_state(panel).rename(columns={"broken_ratio": "broken_ratio_market"})
    theme = build_theme_state(panel)
    enriched = add_roles(panel, theme, market)
    enriched = core.add_research_features(enriched)
    enriched, universe_meta = enforce_universe_policy(enriched)
    enriched = core.attach_forward_returns(enriched, config.round_trip_cost)

    split = pd.Timestamp(config.oos_start)
    report: dict[str, Any] = {
        "config": asdict(config),
        "data": {**metadata, **universe_meta},
        "methodology": {
            "signal": "completed daily state only; no future event/price fields",
            "universe": universe_meta["policy"],
            "entry": "next available open; locked upper-limit session is unfilled",
            "horizons": "entry T+1 open to T+2/T+3/T+6 open for 1/2/5d labels",
            "cost": config.round_trip_cost,
            "baseline": "same-date eligible universe average executable return",
            "control": "pre-registered hypothesis-specific same-context control",
            "bootstrap_unit": "signal date",
            "parameter_policy": "broad pre-registered thresholds; no threshold search",
            "promotion_policy": "daily screen only promotes information; minute-required hypotheses are not trade-ready",
        },
        "hypotheses": {},
        "oos_bin_diagnostics": core.bin_diagnostics(enriched, split, config),
    }

    observations: list[pd.DataFrame] = []
    for index, hypothesis in enumerate(core.hypotheses()):
        selected_mask = hypothesis.selector(enriched).fillna(False)
        control_mask = hypothesis.control(enriched).fillna(False) & ~selected_mask
        selected = enriched.loc[selected_mask].copy()
        control = enriched.loc[control_mask].copy()

        columns = _observation_columns(enriched)
        for group_name, group in (("selected", selected), ("control", control)):
            if group.empty:
                continue
            obs = group[columns].copy()
            obs["hypothesis_id"] = hypothesis.id
            obs["group"] = group_name
            observations.append(obs)

        item: dict[str, Any] = {
            "title": hypothesis.title,
            "source_cluster": hypothesis.source_cluster,
            "expected_direction": hypothesis.expected_direction,
            "minute_required": hypothesis.minute_required,
            "notes": hypothesis.notes,
            "development": {},
            "oos": {},
        }
        verdicts: list[str] = []
        for horizon in (1, 2, 5):
            dev_selected = selected.loc[selected["date"] < split]
            dev_control = control.loc[control["date"] < split]
            oos_selected = selected.loc[selected["date"] >= split]
            oos_control = control.loc[control["date"] >= split]

            dev_sel_metrics = core.sample_metrics(dev_selected, horizon, config, index * 40 + horizon)
            dev_ctl_metrics = core.sample_metrics(dev_control, horizon, config, index * 40 + horizon + 5)
            dev_pair = core.paired_difference(
                dev_selected, dev_control, horizon, hypothesis.expected_direction,
                config, index * 40 + horizon + 10,
            )
            oos_sel_metrics = core.sample_metrics(oos_selected, horizon, config, index * 40 + horizon + 15)
            oos_ctl_metrics = core.sample_metrics(oos_control, horizon, config, index * 40 + horizon + 20)
            oos_pair = core.paired_difference(
                oos_selected, oos_control, horizon, hypothesis.expected_direction,
                config, index * 40 + horizon + 25,
            )
            verdict = core._verdict(dev_pair, oos_sel_metrics, oos_pair, hypothesis, config)
            verdicts.append(verdict)
            item["development"][f"{horizon}d"] = {
                "selected": dev_sel_metrics,
                "control": dev_ctl_metrics,
                "paired": dev_pair,
            }
            item["oos"][f"{horizon}d"] = {
                "selected": oos_sel_metrics,
                "control": oos_ctl_metrics,
                "paired": oos_pair,
                "verdict": verdict,
            }

        severity = {
            "FAIL_SIGN_FLIP": 0,
            "FAIL": 1,
            "WEAK_TOP_TAIL_DEPENDENT": 2,
            "WEAK_PERIOD_CONCENTRATED": 3,
            "WEAK_CONTROL_ONLY": 4,
            "INSUFFICIENT_CONTROL": 5,
            "INSUFFICIENT": 6,
            "PROMISING": 7,
            "PASS": 8,
        }
        item["overall_verdict"] = min(verdicts, key=lambda value: severity.get(value, 0))
        report["hypotheses"][hypothesis.id] = item

    output = ROOT / config.output
    observations_output = ROOT / config.observations_output
    output.parent.mkdir(parents=True, exist_ok=True)
    observations_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if observations:
        pd.concat(observations, ignore_index=True).to_parquet(
            observations_output, index=False, compression="zstd"
        )

    concise = {
        key: value["overall_verdict"]
        for key, value in report["hypotheses"].items()
    }
    print(json.dumps(concise, ensure_ascii=False, indent=2))
    return report


def parse_args() -> ScreenConfig:
    parser = argparse.ArgumentParser(description="Canonical v2 book alpha daily hypothesis screen")
    parser.add_argument("--universe", default=ScreenConfig.universe)
    parser.add_argument("--start", default=ScreenConfig.start)
    parser.add_argument("--end", default=ScreenConfig.end)
    parser.add_argument("--oos-start", default=ScreenConfig.oos_start)
    parser.add_argument("--round-trip-cost", type=float, default=ScreenConfig.round_trip_cost)
    parser.add_argument("--bootstrap-samples", type=int, default=ScreenConfig.bootstrap_samples)
    parser.add_argument("--seed", type=int, default=ScreenConfig.seed)
    parser.add_argument("--min-oos-observations", type=int, default=ScreenConfig.min_oos_observations)
    parser.add_argument("--min-oos-days", type=int, default=ScreenConfig.min_oos_days)
    parser.add_argument("--output", default="output/book_alpha_daily_screen_v2.json")
    parser.add_argument("--observations-output", default="output/book_alpha_daily_screen_observations_v2.parquet")
    return ScreenConfig(**vars(parser.parse_args()))


if __name__ == "__main__":
    run(parse_args())
