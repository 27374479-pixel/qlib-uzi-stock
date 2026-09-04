"""Causal first-stage screen for hypotheses extracted from the two 48-trader books.

The purpose is *falsification*, not parameter mining.  Every hypothesis below
has a pre-declared selector and a same-context control.  We measure:

* next-open executable returns after costs;
* date-neutral excess versus the eligible universe on the same signal date;
* paired selected-vs-control differences on dates where both exist;
* development vs 2023+ OOS sign consistency;
* date bootstrap confidence intervals;
* performance after removing the best 5% of individual observations;
* half-year stability.

The screen deliberately reuses ``daily_event_role_backtest`` for point-in-time
membership, ST/tradability filtering, price-limit rules, market/theme state and
role construction.  It does not claim that daily bars validate an intraday
entry.  Survivors marked ``minute_required`` must later pass a fixed-signal
5-minute replay.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from daily_event_role_backtest import (
    Config as EventConfig,
    add_roles,
    build_market_state,
    build_theme_state,
    load_panel,
)

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ScreenConfig:
    universe: str = "csi800"
    start: str = "2015-01-01"
    end: str = "2026-09-03"
    oos_start: str = "2023-01-01"
    round_trip_cost: float = 0.0018
    bootstrap_samples: int = 5000
    seed: int = 20260904
    min_oos_observations: int = 50
    min_oos_days: int = 20
    output: str = "output/book_alpha_daily_screen_v1.json"
    observations_output: str = "output/book_alpha_daily_screen_observations_v1.parquet"


@dataclass(frozen=True)
class Hypothesis:
    id: str
    title: str
    source_cluster: str
    selector: Callable[[pd.DataFrame], pd.Series]
    control: Callable[[pd.DataFrame], pd.Series]
    expected_direction: int = 1  # +1 means selected > control; -1 means selected < control.
    minute_required: bool = False
    positive_selected_required: bool = True
    notes: str = ""


def _bool(frame: pd.DataFrame, column: str, default: bool = False) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=bool)
    return frame[column].fillna(default).astype(bool)


def _num(frame: pd.DataFrame, column: str, default: float = np.nan) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def add_research_features(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_values(["instrument", "date"]).copy()
    by_stock = frame.groupby("instrument", sort=False)
    frame["ma10"] = by_stock["close"].transform(lambda x: x.rolling(10, min_periods=8).mean())
    frame["ma20"] = by_stock["close"].transform(lambda x: x.rolling(20, min_periods=15).mean())
    frame["ma60"] = by_stock["close"].transform(lambda x: x.rolling(60, min_periods=40).mean())
    frame["ret20"] = frame["close"] / by_stock["close"].shift(20) - 1.0
    frame["ret60"] = frame["close"] / by_stock["close"].shift(60) - 1.0
    frame["price_to_ma20"] = frame["close"] / frame["ma20"] - 1.0
    frame["price_to_ma60"] = frame["close"] / frame["ma60"] - 1.0
    rolling_high20 = by_stock["close"].transform(lambda x: x.rolling(20, min_periods=15).max())
    frame["drawdown20"] = frame["close"] / rolling_high20 - 1.0

    # Previous market state is created from unique dates so the shift is not
    # accidentally performed once per stock row.
    market_by_date = (
        frame[["date", "weak_market", "breadth", "money_effect", "broken_ratio_market"]]
        .drop_duplicates("date")
        .sort_values("date")
        .copy()
    )
    market_by_date["prev_weak_market"] = market_by_date["weak_market"].shift(1)
    market_by_date["prev_breadth"] = market_by_date["breadth"].shift(1)
    market_by_date["breadth_change"] = market_by_date["breadth"] - market_by_date["prev_breadth"]
    frame = frame.merge(
        market_by_date[["date", "prev_weak_market", "breadth_change"]],
        on="date",
        how="left",
    )

    # Executable forward returns.  Entry is next available trading row's open.
    # A next session that never trades below its upper limit is marked unfilled.
    frame = frame.sort_values(["instrument", "date"]).reset_index(drop=True)
    by_stock = frame.groupby("instrument", sort=False)
    frame["entry_date"] = by_stock["date"].shift(-1)
    frame["entry_open"] = by_stock["open"].shift(-1)
    frame["entry_low"] = by_stock["low"].shift(-1)
    frame["entry_upper_limit"] = by_stock["upper_limit"].shift(-1)
    frame["entry_filled"] = (
        frame["entry_open"].notna()
        & frame["entry_low"].notna()
        & ~(
            (frame["entry_open"] >= frame["entry_upper_limit"] - 0.011)
            & (frame["entry_low"] >= frame["entry_upper_limit"] - 0.011)
        )
    )
    return frame


def attach_forward_returns(frame: pd.DataFrame, cost: float) -> pd.DataFrame:
    frame = frame.sort_values(["instrument", "date"]).copy()
    by_stock = frame.groupby("instrument", sort=False)
    for horizon in (1, 2, 5):
        exit_open = by_stock["open"].shift(-(1 + horizon))
        raw = exit_open / frame["entry_open"] - 1.0 - cost
        frame[f"return_{horizon}d"] = raw.where(frame["entry_filled"])
        baseline = frame.groupby("date")[f"return_{horizon}d"].transform("mean")
        frame[f"market_excess_{horizon}d"] = frame[f"return_{horizon}d"] - baseline
    return frame


def _core_base(f: pd.DataFrame) -> pd.Series:
    return _bool(f, "core") & ~_bool(f, "one_word")


def _prior_active(f: pd.DataFrame) -> pd.Series:
    return _num(f, "prior_seal5", 0).fillna(0).gt(0) | _num(f, "prior_touch20", 0).fillna(0).gt(0)


def hypotheses() -> list[Hypothesis]:
    return [
        Hypothesis(
            "H01", "weak-regime veto", "养家/Asking/瑞鹤仙/孤独牛背",
            lambda f: _core_base(f) & _prior_active(f) & ~_bool(f, "weak_market", True),
            lambda f: _core_base(f) & _prior_active(f) & _bool(f, "weak_market", True),
            positive_selected_required=True,
            notes="Same active-core family; non-weak market should dominate weak market.",
        ),
        Hypothesis(
            "H02", "panic-to-repair", "养家弱势超跌/Asking/乔帮主",
            lambda f: _core_base(f) & _bool(f, "prev_weak_market") & ~_bool(f, "weak_market", True)
            & _num(f, "breadth_change", 0).gt(0.12) & _num(f, "drawdown20", 0).lt(-0.06),
            lambda f: _core_base(f) & _num(f, "drawdown20", 0).lt(-0.06)
            & ~(_bool(f, "prev_weak_market") & ~_bool(f, "weak_market", True) & _num(f, "breadth_change", 0).gt(0.12)),
            minute_required=True,
            notes="Tests collective repair versus merely being individually oversold.",
        ),
        Hypothesis(
            "H03", "climax avoidance", "情绪周期/高潮后分歧",
            lambda f: _core_base(f) & _bool(f, "climax"),
            lambda f: _core_base(f) & (_bool(f, "emergence") | _bool(f, "divergence") | _bool(f, "repair")) & ~_bool(f, "climax"),
            expected_direction=-1,
            positive_selected_required=False,
            notes="A successful veto means climax chasing is worse than non-climax core states.",
        ),
        Hypothesis(
            "H04", "novelty-emergence", "赵老哥/作手新一/陈小群",
            lambda f: _core_base(f) & _bool(f, "emergence") & _num(f, "prior_event20", 99).le(3),
            lambda f: _core_base(f) & _num(f, "first_board_n", 0).ge(2) & _num(f, "prior_event20", 0).gt(3),
            notes="Current industry event proxy is provisional; true event text is a later upgrade.",
        ),
        Hypothesis(
            "H05", "breadth-with-leader", "主线/合力/热点中的热点",
            lambda f: _core_base(f) & _num(f, "positive_ratio", 0).ge(0.60),
            lambda f: _core_base(f) & _num(f, "positive_ratio", 1).le(0.40),
            notes="Leader plus broad participation versus isolated strong stock.",
        ),
        Hypothesis(
            "H06", "post-divergence repair", "养家/涅槃重升/乔帮主",
            lambda f: _core_base(f) & _bool(f, "repair") & _prior_active(f),
            lambda f: _core_base(f) & _bool(f, "climax") & _prior_active(f),
            minute_required=True,
        ),
        Hypothesis(
            "H07", "survivor-not-follower", "龙头/淘汰赛/幸存者",
            lambda f: _bool(f, "divergence") & _prior_active(f) & _num(f, "ret_rank", 0).ge(0.75)
            & _num(f, "ret1", 0).between(-0.045, 0.065),
            lambda f: _bool(f, "divergence") & ~_prior_active(f) & _num(f, "ret_rank", 0).ge(0.75),
            minute_required=True,
        ),
        Hypothesis(
            "H08", "role persistence", "赵老哥/养家/陈小群/作手新一",
            lambda f: _core_base(f) & _prior_active(f),
            lambda f: ~_prior_active(f) & _num(f, "ret_rank", 0).ge(0.90) & _num(f, "amount_rank", 0).ge(0.70)
            & ~_bool(f, "one_word"),
            notes="Persistent role versus same-day strength without prior role evidence.",
        ),
        Hypothesis(
            "H10", "amount acceleration sweet zone", "放量/资金合力/分歧成交额",
            lambda f: _core_base(f) & _prior_active(f) & _num(f, "amount_accel", 0).between(1.20, 2.00),
            lambda f: _core_base(f) & _prior_active(f) & _num(f, "amount_accel", 0).between(0.80, 1.20, inclusive="left"),
            notes="Pre-registered moderate acceleration; >2x is reported separately as possible distribution.",
        ),
        Hypothesis(
            "H11", "turnover sweet spot", "板板换手/供给释放",
            lambda f: _core_base(f) & _prior_active(f) & _num(f, "turnover_rate_pct", 0).between(3.0, 15.0),
            lambda f: _core_base(f) & _prior_active(f)
            & (_num(f, "turnover_rate_pct", 0).lt(1.0) | _num(f, "turnover_rate_pct", 0).gt(25.0)),
            notes="Tests inverted-U intuition rather than optimizing one turnover threshold.",
        ),
        Hypothesis(
            "H13", "price-under-10 placebo", "上册低价经验规则",
            lambda f: _core_base(f) & _prior_active(f) & _num(f, "close", np.nan).lt(10.0),
            lambda f: _core_base(f) & _prior_active(f) & _num(f, "close", np.nan).ge(10.0),
            positive_selected_required=False,
            notes="Modifier/placebo only; never a standalone trading trigger.",
        ),
        Hypothesis(
            "H14", "high-volume divergence", "上册高量分歧/成交额",
            lambda f: _bool(f, "divergence") & _prior_active(f) & _num(f, "ret_rank", 0).ge(0.75)
            & _num(f, "amount_accel", 0).ge(1.50),
            lambda f: _bool(f, "divergence") & _prior_active(f) & _num(f, "ret_rank", 0).ge(0.75)
            & _num(f, "amount_accel", 99).lt(1.20),
            minute_required=True,
        ),
        Hypothesis(
            "H15", "trend pullback", "乔帮主/糊涂118低吸",
            lambda f: _prior_active(f) & _num(f, "ret60", 0).gt(0.08) & _num(f, "ret5", 0).lt(0)
            & _num(f, "price_to_ma20", 99).between(-0.03, 0.03) & ~_bool(f, "weak_market", True),
            lambda f: _num(f, "ret5", 0).lt(0) & _num(f, "drawdown20", 0).between(-0.15, -0.03)
            & _num(f, "ret60", 0).lt(0),
            minute_required=True,
            notes="Strong-trend pullback versus similarly weak recent return in a downtrend.",
        ),
    ]


def _ci(values: np.ndarray, samples: int, seed: int) -> tuple[float | None, float | None]:
    values = values[np.isfinite(values)]
    if values.size < 8:
        return None, None
    rng = np.random.default_rng(seed)
    means = np.empty(samples, dtype=float)
    for i in range(samples):
        means[i] = rng.choice(values, size=len(values), replace=True).mean()
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def _halfyear_key(dates: pd.Series) -> pd.Series:
    dates = pd.to_datetime(dates)
    half = np.where(dates.dt.month <= 6, "H1", "H2")
    return dates.dt.year.astype(str) + half


def sample_metrics(sample: pd.DataFrame, horizon: int, config: ScreenConfig, seed_offset: int = 0) -> dict[str, Any]:
    col = f"return_{horizon}d"
    excess_col = f"market_excess_{horizon}d"
    x = sample.loc[sample["entry_filled"].fillna(False) & sample[col].notna() & sample[excess_col].notna()].copy()
    if x.empty:
        return {"n": 0, "active_days": 0}
    day = x.groupby("date", sort=True).agg(return_mean=(col, "mean"), excess_mean=(excess_col, "mean"))
    ci_low, ci_high = _ci(day["excess_mean"].to_numpy(float), config.bootstrap_samples, config.seed + seed_offset)
    cutoff = x[col].quantile(0.95) if len(x) >= 20 else np.inf
    trimmed = x.loc[x[col] <= cutoff]
    trimmed_day = trimmed.groupby("date")[excess_col].mean() if not trimmed.empty else pd.Series(dtype=float)
    half = day.reset_index()
    half["half"] = _halfyear_key(half["date"])
    half_values = half.groupby("half")["excess_mean"].mean()
    return {
        "n": int(len(x)),
        "active_days": int(len(day)),
        "mean_return": float(x[col].mean()),
        "median_return": float(x[col].median()),
        "win_rate": float((x[col] > 0).mean()),
        "mean_market_excess": float(day["excess_mean"].mean()),
        "bootstrap95_market_excess": [ci_low, ci_high],
        "trim_best5_mean_market_excess": float(trimmed_day.mean()) if len(trimmed_day) else None,
        "halfyears": int(len(half_values)),
        "positive_halfyears": int((half_values > 0).sum()),
        "negative_halfyears": int((half_values < 0).sum()),
        "best_half_contribution_share": _best_period_share(half_values),
    }


def _best_period_share(values: pd.Series) -> float | None:
    if values.empty:
        return None
    positives = values.clip(lower=0)
    total = float(positives.sum())
    if total <= 0:
        return None
    return float(positives.max() / total)


def paired_difference(selected: pd.DataFrame, control: pd.DataFrame, horizon: int, direction: int, config: ScreenConfig, seed_offset: int = 0) -> dict[str, Any]:
    col = f"return_{horizon}d"
    a = selected.loc[selected["entry_filled"].fillna(False) & selected[col].notna()].groupby("date")[col].mean()
    b = control.loc[control["entry_filled"].fillna(False) & control[col].notna()].groupby("date")[col].mean()
    pair = pd.concat([a.rename("selected"), b.rename("control")], axis=1, join="inner").dropna()
    if pair.empty:
        return {"paired_days": 0}
    pair["raw_diff"] = pair["selected"] - pair["control"]
    pair["signed_diff"] = direction * pair["raw_diff"]
    ci_low, ci_high = _ci(pair["signed_diff"].to_numpy(float), config.bootstrap_samples, config.seed + 1000 + seed_offset)
    half = pair.reset_index()
    half["half"] = _halfyear_key(half["date"])
    half_values = half.groupby("half")["signed_diff"].mean()
    return {
        "paired_days": int(len(pair)),
        "selected_minus_control": float(pair["raw_diff"].mean()),
        "expected_signed_difference": float(pair["signed_diff"].mean()),
        "bootstrap95_expected_signed_difference": [ci_low, ci_high],
        "positive_halfyears_expected_direction": int((half_values > 0).sum()),
        "negative_halfyears_expected_direction": int((half_values < 0).sum()),
        "halfyears": int(len(half_values)),
        "best_half_contribution_share": _best_period_share(half_values),
    }


def _verdict(dev_pair: dict[str, Any], oos_sel: dict[str, Any], oos_pair: dict[str, Any], h: Hypothesis, config: ScreenConfig) -> str:
    if oos_sel.get("n", 0) < config.min_oos_observations or oos_sel.get("active_days", 0) < config.min_oos_days:
        return "INSUFFICIENT"
    if oos_pair.get("paired_days", 0) < max(10, config.min_oos_days // 2):
        return "INSUFFICIENT_CONTROL"
    oos_diff = oos_pair.get("expected_signed_difference")
    dev_diff = dev_pair.get("expected_signed_difference")
    if oos_diff is None or not np.isfinite(oos_diff) or oos_diff <= 0:
        return "FAIL"
    if dev_diff is not None and np.isfinite(dev_diff) and dev_diff <= 0:
        return "FAIL_SIGN_FLIP"
    if h.positive_selected_required:
        if (oos_sel.get("mean_market_excess") or -99) <= 0:
            return "WEAK_CONTROL_ONLY"
        trim = oos_sel.get("trim_best5_mean_market_excess")
        if trim is not None and trim <= 0:
            return "WEAK_TOP_TAIL_DEPENDENT"
    best_share = oos_pair.get("best_half_contribution_share")
    if best_share is not None and best_share > 0.50:
        return "WEAK_PERIOD_CONCENTRATED"
    ci = oos_pair.get("bootstrap95_expected_signed_difference") or [None, None]
    if ci[0] is not None and ci[0] > 0:
        return "PASS"
    return "PROMISING"


def bin_diagnostics(frame: pd.DataFrame, split: pd.Timestamp, config: ScreenConfig) -> dict[str, Any]:
    oos = frame.loc[frame["date"] >= split & frame["entry_filled"].fillna(False)].copy() if False else frame.loc[(frame["date"] >= split) & frame["entry_filled"].fillna(False)].copy()
    core = oos.loc[_core_base(oos) & _prior_active(oos)].copy()
    result: dict[str, Any] = {}
    if core.empty:
        return result
    core["amount_bin"] = pd.cut(_num(core, "amount_accel"), [-np.inf, 0.8, 1.2, 2.0, np.inf], labels=["lt0.8", "0.8-1.2", "1.2-2.0", "gt2.0"], right=False)
    core["turnover_bin"] = pd.cut(_num(core, "turnover_rate_pct"), [-np.inf, 1, 3, 15, 25, np.inf], labels=["lt1", "1-3", "3-15", "15-25", "gt25"], right=False)
    core["price_bin"] = pd.cut(_num(core, "close"), [-np.inf, 10, 20, 50, np.inf], labels=["lt10", "10-20", "20-50", "gte50"], right=False)
    core["board_bin"] = pd.cut(_num(core, "board_height", 0), [-1, 0, 1, 2, np.inf], labels=["0", "1", "2", "3plus"], right=True)
    for name in ("amount_bin", "turnover_bin", "price_bin", "board_bin"):
        groups: dict[str, Any] = {}
        for value, group in core.groupby(name, observed=True):
            groups[str(value)] = {f"return_{h}d": sample_metrics(group, h, config, 7000 + h) for h in (1, 2, 5)}
        result[name] = groups
    return result


def run(config: ScreenConfig) -> dict[str, Any]:
    event_config = EventConfig(universe=config.universe, start=config.start, end=config.end)
    panel, metadata = load_panel(event_config)
    market = build_market_state(panel)
    # Name market broken ratio explicitly before add_roles; theme has its own broken_ratio.
    market = market.rename(columns={"broken_ratio": "broken_ratio_market"})
    theme = build_theme_state(panel)
    enriched = add_roles(panel, theme, market)
    enriched = add_research_features(enriched)
    enriched = attach_forward_returns(enriched, config.round_trip_cost)

    split = pd.Timestamp(config.oos_start)
    report: dict[str, Any] = {
        "config": asdict(config),
        "data": metadata,
        "methodology": {
            "signal": "completed daily state only",
            "entry": "next available open; locked upper-limit session is unfilled",
            "horizons": "entry T+1 open to T+2/T+3/T+6 open for 1/2/5d labels",
            "cost": config.round_trip_cost,
            "baseline": "same-date eligible universe average executable return",
            "control": "pre-registered hypothesis-specific same-context control",
            "bootstrap_unit": "signal date",
            "parameter_policy": "pre-registered broad thresholds; no threshold search in this script",
        },
        "hypotheses": {},
        "oos_bin_diagnostics": bin_diagnostics(enriched, split, config),
    }
    observations: list[pd.DataFrame] = []
    for index, hypothesis in enumerate(hypotheses()):
        selected_mask = hypothesis.selector(enriched).fillna(False)
        control_mask = hypothesis.control(enriched).fillna(False) & ~selected_mask
        selected = enriched.loc[selected_mask].copy()
        control = enriched.loc[control_mask].copy()
        if not selected.empty:
            s = selected[["date", "instrument", "entry_date", "entry_filled", "close", "setup" if "setup" in selected.columns else "instrument"] + [f"return_{h}d" for h in (1,2,5)] + [f"market_excess_{h}d" for h in (1,2,5)]].copy()
            s["hypothesis_id"] = hypothesis.id
            s["group"] = "selected"
            observations.append(s)
        if not control.empty:
            c = control[["date", "instrument", "entry_date", "entry_filled", "close"] + [f"return_{h}d" for h in (1,2,5)] + [f"market_excess_{h}d" for h in (1,2,5)]].copy()
            c["hypothesis_id"] = hypothesis.id
            c["group"] = "control"
            observations.append(c)

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
            dev_sel = sample_metrics(selected.loc[selected["date"] < split], horizon, config, index * 30 + horizon)
            dev_ctl = sample_metrics(control.loc[control["date"] < split], horizon, config, index * 30 + horizon + 5)
            dev_pair = paired_difference(selected.loc[selected["date"] < split], control.loc[control["date"] < split], horizon, hypothesis.expected_direction, config, index * 30 + horizon)
            oos_sel = sample_metrics(selected.loc[selected["date"] >= split], horizon, config, index * 30 + horizon + 10)
            oos_ctl = sample_metrics(control.loc[control["date"] >= split], horizon, config, index * 30 + horizon + 15)
            oos_pair = paired_difference(selected.loc[selected["date"] >= split], control.loc[control["date"] >= split], horizon, hypothesis.expected_direction, config, index * 30 + horizon + 20)
            verdict = _verdict(dev_pair, oos_sel, oos_pair, hypothesis, config)
            verdicts.append(verdict)
            item["development"][f"{horizon}d"] = {"selected": dev_sel, "control": dev_ctl, "paired": dev_pair}
            item["oos"][f"{horizon}d"] = {"selected": oos_sel, "control": oos_ctl, "paired": oos_pair, "verdict": verdict}
        priority = ["FAIL_SIGN_FLIP", "FAIL", "WEAK_TOP_TAIL_DEPENDENT", "WEAK_PERIOD_CONCENTRATED", "WEAK_CONTROL_ONLY", "INSUFFICIENT_CONTROL", "INSUFFICIENT", "PROMISING", "PASS"]
        # Overall verdict is conservative: the weakest sufficiently-observed horizon dominates.
        item["overall_verdict"] = min(verdicts, key=lambda v: priority.index(v) if v in priority else 0)
        report["hypotheses"][hypothesis.id] = item

    output = ROOT / config.output
    obs_output = ROOT / config.observations_output
    output.parent.mkdir(parents=True, exist_ok=True)
    obs_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if observations:
        pd.concat(observations, ignore_index=True).to_parquet(obs_output, index=False, compression="zstd")
    print(json.dumps({k: v["overall_verdict"] for k, v in report["hypotheses"].items()}, ensure_ascii=False, indent=2))
    return report


def parse_args() -> ScreenConfig:
    parser = argparse.ArgumentParser(description="Screen book-derived alpha hypotheses without threshold mining")
    parser.add_argument("--universe", default=ScreenConfig.universe)
    parser.add_argument("--start", default=ScreenConfig.start)
    parser.add_argument("--end", default=ScreenConfig.end)
    parser.add_argument("--oos-start", default=ScreenConfig.oos_start)
    parser.add_argument("--round-trip-cost", type=float, default=ScreenConfig.round_trip_cost)
    parser.add_argument("--bootstrap-samples", type=int, default=ScreenConfig.bootstrap_samples)
    parser.add_argument("--seed", type=int, default=ScreenConfig.seed)
    parser.add_argument("--min-oos-observations", type=int, default=ScreenConfig.min_oos_observations)
    parser.add_argument("--min-oos-days", type=int, default=ScreenConfig.min_oos_days)
    parser.add_argument("--output", default=ScreenConfig.output)
    parser.add_argument("--observations-output", default=ScreenConfig.observations_output)
    return ScreenConfig(**vars(parser.parse_args()))


if __name__ == "__main__":
    run(parse_args())
