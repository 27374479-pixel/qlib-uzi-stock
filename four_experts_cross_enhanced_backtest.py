"""Cross-enhanced replay for four public short-term trading styles.

This module is intentionally separate from ``five_experts_intraday_backtest_v2``.
The latter remains the pure, style-specific proxy.  This file tests a new
research hypothesis: borrow only the parts of later chapters that can be
observed before or at the entry bar, and require them in a two-stage process:

    prior plan / market permission -> current confirmation / execution

The four styles are 职业炒手, Asking, 赵老哥 and 冷狐冲.  The output calls this
``cross_enhanced`` rather than attributing the combined rules to any one
trader.  It does not use end-of-day results from the signal day, auction data
that are not in the local minute panel, or future bars in the signal rule.

The model is a research proxy.  It cannot reproduce private watchlists,
order-queue information, news interpretation, or discretionary exits.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import five_experts_intraday_backtest as base
import five_experts_intraday_backtest_v2 as v2
from config import OUTPUT_DIR, PROJECT_ROOT


STYLES = ("zhiye", "asking", "zhao", "lenghuchong")
VARIANT = "cross_enhanced"


def _series(frame: pd.DataFrame, name: str, default: float | bool | str = np.nan) -> pd.Series:
    """Return a frame column without silently changing the row index."""

    if name in frame:
        return frame[name]
    return pd.Series(default, index=frame.index)


def _bool(frame: pd.DataFrame, name: str, default: bool = False) -> pd.Series:
    return _series(frame, name, default).fillna(default).astype(bool)


def _num(frame: pd.DataFrame, name: str, default: float = np.nan) -> pd.Series:
    return pd.to_numeric(_series(frame, name, default), errors="coerce")


def _amount_quality(series: pd.Series) -> pd.Series:
    """Prefer usable turnover; penalise both illiquidity and blow-up volume."""

    return (
        1.0 - np.log(series.clip(0.25, 8.0) / 1.15).abs() / np.log(8.0)
    ).clip(0.0, 1.0)


def _cross_context(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Build observable context used by all four enhanced styles.

    Every input is either a prior completed day, a prior event pool, or a
    current-day as-of field already cut at the signal timestamp.
    """

    market_phase = _series(frame, "market_phase", "fear").astype(str)
    prior_fear = _bool(frame, "prior_daily_fear")
    # ``daily_fear`` is intentionally conservative and, in this partial
    # universe, can stay true because of a high broken-board ratio alone.  A
    # hard prior veto therefore needs corroboration from a completed-day
    # breadth/return deterioration; otherwise a neutral current session is
    # treated as a possible transition rather than an automatic empty day.
    prior_hard_fear = prior_fear & (
        (
            (_num(frame, "prior_market_breadth") < -0.18)
            & (_num(frame, "prior_market_ret3") < -0.015)
        )
        | (
            (_num(frame, "prior_market_down_ratio") > 0.35)
            & (_num(frame, "prior_market_ret3") < 0.0)
        )
    )
    index_supportive = _bool(frame, "index_supportive", True)
    index_risk = _bool(frame, "index_risk_contraction")
    current_not_fear = market_phase.ne("fear")

    # Later chapters repeatedly describe "主流/热点" and "龙头".  The
    # local cache has Eastmoney themes only for some dates, so a missing or
    # undecoded theme is explicitly treated as an industry-cohort proxy, not
    # as a real news/theme label.
    event_evidence = (
        (_num(frame, "prior_event_limit_up_stock", 0.0) > 0)
        | (_num(frame, "prior_event_previous_limit_up_stock", 0.0) > 0)
        | (_num(frame, "prior_event_board_days") > 0)
        | _series(frame, "prior_event_theme", "").fillna("").astype(str).ne("")
    )
    event_available = _bool(frame, "prior_event_data_available")
    prior_board_evidence = event_evidence | (_num(frame, "prior_prior_limit_up5", 0.0) >= 1)

    # "主线" proxy: at least a small cohort is rising together with usable
    # turnover.  This avoids declaring an isolated stock a theme leader.
    group_attack = _bool(frame, "group_attack")
    group_ready = (
        (_num(frame, "group_n", 0) >= 4)
        & (_num(frame, "group_breadth") > 0.05)
        & (_num(frame, "group_return_median") > -0.002)
        & (_num(frame, "group_amount_median") > 0.50)
    )
    cohort_support = group_ready & (_num(frame, "group_relative_return") > -0.012)

    # Leader rank is only a ranking within the information available at the
    # cutoff.  It is not a claim that the stock will be the future leader.
    leader_rank = (
        0.42 * _num(frame, "group_intraday_rank", 0.0).fillna(0.0)
        + 0.35 * _num(frame, "rank_intraday", 0.0).fillna(0.0)
        + 0.23 * _num(frame, "group_prior10_rank", 0.0).fillna(0.0)
    )

    prior_strength = (
        (_num(frame, "prior_ret10") > 0.035)
        | (_num(frame, "prior_ret5") > 0.018)
        | prior_board_evidence
    )
    no_chase = (
        (_num(frame, "gap_to_upper") > -0.055)
        & (_num(frame, "from_high") > -0.085)
        & (_num(frame, "intraday_return") < 0.085)
    )
    amount_ok = _num(frame, "amount_ratio_asof").between(0.55, 3.80)
    active = ~_bool(frame, "locked_upper")
    support = (
        current_not_fear
        & index_supportive
        & (~prior_hard_fear | _bool(frame, "market_transition"))
        & (
            (market_phase == "money_making")
            | (
                (market_phase == "neutral")
                & (_num(frame, "market_breadth") > -0.02)
                & (_num(frame, "market_down_ratio_2") < 0.30)
                # The local minute panel has an unusually high partial-day
                # broken ratio; keep it as a soft quality bound rather than
                # turning every neutral snapshot into a no-trade state.
                & (_num(frame, "broken_ratio") < 0.98)
            )
        )
    )
    # On a broad-index contraction, only an explicit transition/rebound setup
    # may proceed.  This is a veto, not a score bonus.
    rebound_exception = _bool(frame, "collective_oversold") & _bool(frame, "market_transition")
    risk_gate = (~index_risk) | rebound_exception
    risk_reward = _num(frame, "reward_risk_proxy")

    return {
        "market_phase": market_phase,
        "prior_fear": prior_fear,
        "prior_hard_fear": prior_hard_fear,
        "event_evidence": event_evidence,
        "event_available": event_available,
        "prior_board_evidence": prior_board_evidence,
        "group_attack": group_attack,
        "group_ready": group_ready,
        "cohort_support": cohort_support,
        "leader_rank": leader_rank,
        "prior_strength": prior_strength,
        "no_chase": no_chase,
        "amount_ok": amount_ok,
        "active": active,
        "support": support,
        "risk_gate": risk_gate,
        "risk_reward": risk_reward,
    }


def apply_cross_rule(
    frame: pd.DataFrame, style: str
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Return trigger, score, reason, mode and invalidation for one cutoff."""

    if style not in STYLES:
        raise KeyError(style)
    ctx = _cross_context(frame)
    phase = ctx["market_phase"]
    support = ctx["support"]
    active = ctx["active"]
    amount_ok = ctx["amount_ok"]
    cohort = ctx["cohort_support"]
    group_attack = ctx["group_attack"]
    leader_rank = ctx["leader_rank"]
    prior_strength = ctx["prior_strength"]
    no_chase = ctx["no_chase"]
    risk_gate = ctx["risk_gate"]
    rr = ctx["risk_reward"]

    # A practical proxy for "do not buy if the expected space is obviously
    # smaller than the observed risk".  Board execution gets a looser gate
    # because its profit source is continuation rather than a prior range high.
    rr_ok = rr.ge(1.20) | rr.isna()

    trigger = pd.Series(False, index=frame.index)
    score = pd.Series(-np.inf, index=frame.index, dtype=float)
    mode = pd.Series("no_trade", index=frame.index, dtype=object)
    reason = pd.Series("NO_TRADE", index=frame.index, dtype=object)
    invalidation = pd.Series("市场/板块/个股承接条件失效", index=frame.index, dtype=object)

    if style == "zhiye":
        # 职业炒手 + later chapters: right-side trend, or a strong-stock
        # pullback that has actually stabilised.  Do not buy the falling knife
        # just because it was strong yesterday.
        trend = (
            support
            & risk_gate
            & cohort
            & prior_strength
            & (_num(frame, "prior_ret1") < 0.085)
            & _num(frame, "intraday_return").between(0.010, 0.075)
            & (_num(frame, "from_open") > 0.002)
            & (_num(frame, "from_high") > -0.038)
            & (_num(frame, "group_breadth") > 0.08)
            & (_num(frame, "group_return_median") > 0.002)
            & (_num(frame, "group_relative_return") > -0.006)
            & (leader_rank >= 0.68)
            & no_chase
            & rr_ok
        )
        pullback = (
            support
            & risk_gate
            & cohort
            & prior_strength
            & (_num(frame, "prior_ret1") < 0.080)
            & _num(frame, "from_high").between(-0.060, -0.008)
            & (_num(frame, "recovery_from_low") > 0.010)
            & (_num(frame, "late_momentum_30m") > 0.001)
            & _bool(frame, "group_stabilizing")
            & (_num(frame, "group_intraday_rank") >= 0.60)
            & (_num(frame, "group_breadth") > 0.05)
            & no_chase
            & rr_ok
        )
        trigger = active & amount_ok & (trend | pullback)
        mode = pd.Series(
            np.select([trend, pullback], ["right_side_trend", "strong_pullback_confirmation"], default="no_trade"),
            index=frame.index,
            dtype=object,
        )
        reason = pd.Series(
            np.select(
                [trend, pullback],
                [
                    "增强：非退潮环境+主线同步，右侧趋势确认后跟随",
                    "增强：强势股回撤后重新转强，承接与板块同步确认",
                ],
                default="NO_TRADE",
            ),
            index=frame.index,
            dtype=object,
        )
        invalidation = pd.Series(
            "个股跌破承接位、板块中位数转弱、市场退潮或预期空间不足",
            index=frame.index,
            dtype=object,
        )
        score = (
            0.24 * _num(frame, "rank_intraday", 0.0)
            + 0.22 * _num(frame, "rank_prior10", 0.0)
            + 0.18 * _num(frame, "group_intraday_rank", 0.0)
            + 0.14 * _num(frame, "rank_late", 0.0)
            + 0.12 * (rr / 4.0).clip(0.0, 1.0).fillna(0.25)
            + 0.10 * _amount_quality(_num(frame, "amount_ratio_asof"))
        )

    elif style == "asking":
        # Asking-style rhythm is represented as a plan from the previous day
        # followed by a morning/late validation.  Auction fields are absent in
        # this dataset, so the current first 30m response is the explicit
        # substitute and is reported as such in methodology.
        plan = prior_strength | ctx["event_evidence"] | (_num(frame, "group_prior10_median") > 0.020)
        morning_validation = (
            (frame["clock_bucket"] == "morning")
            & support
            & risk_gate
            & plan
            & group_attack
            & (_num(frame, "intraday_return") > 0.012)
            & (_num(frame, "from_open") > 0.004)
            & (_num(frame, "amount_ratio_asof") > 1.00)
            & (_num(frame, "group_intraday_rank") >= 0.75)
            & (_num(frame, "late_momentum_30m") > -0.002)
            & (_num(frame, "gap_to_upper") > -0.050)
            & no_chase
            & rr_ok
        )
        late_retest = (
            (frame["clock_bucket"] == "late")
            & support
            & risk_gate
            & plan
            & cohort
            & (_num(frame, "prior_ret10") > 0.030)
            & _num(frame, "from_high").between(-0.075, -0.012)
            & (_num(frame, "late_momentum_30m") > 0.0015)
            & (_num(frame, "recovery_from_low") > 0.012)
            & (_num(frame, "group_breadth") > 0.05)
            & (_num(frame, "group_intraday_rank") >= 0.65)
            & no_chase
            & rr_ok
        )
        oversold = (
            (frame["clock_bucket"] == "late")
            & _bool(frame, "collective_oversold")
            & _bool(frame, "market_transition")
            & _bool(frame, "collective_stabilizing")
            & (_num(frame, "market_breadth") > -0.05)
            & (_num(frame, "market_median_intraday") > -0.008)
            & (_num(frame, "recovery_from_low") > 0.015)
            & (_num(frame, "late_momentum_30m") > 0.002)
            & _bool(frame, "group_stabilizing")
            & (_num(frame, "group_recovery_rank") >= 0.65)
            & risk_gate
        )
        trigger = active & amount_ok & (morning_validation | late_retest | oversold)
        mode = pd.Series(
            np.select(
                [morning_validation, late_retest, oversold],
                ["planned_morning_validation", "planned_late_retest", "oversold_transition"],
                default="no_trade",
            ),
            index=frame.index,
            dtype=object,
        )
        reason = pd.Series(
            np.select(
                [morning_validation, late_retest, oversold],
                [
                    "增强：前一日有预案，早盘热点扩散与量价确认",
                    "增强：计划内强势股回踩后再转强，等待节奏而非追高",
                    "增强：极端弱势后的市场/板块/个股三层止跌",
                ],
                default="NO_TRADE",
            ),
            index=frame.index,
            dtype=object,
        )
        invalidation = pd.Series(
            "计划主题不扩散、回踩失去承接、市场转退潮或下一根K线不可成交",
            index=frame.index,
            dtype=object,
        )
        score = (
            0.23 * _num(frame, "rank_late", 0.0)
            + 0.21 * _num(frame, "group_intraday_rank", 0.0)
            + 0.18 * _num(frame, "rank_recovery", 0.0)
            + 0.16 * _num(frame, "rank_prior10", 0.0)
            + 0.12 * leader_rank
            + 0.10 * _amount_quality(_num(frame, "amount_ratio_asof"))
        )

    elif style == "zhao":
        # 赵老哥-style public principles are approximated with the later
        # chapters' stricter "主流—龙头—节奏" filter.  Only the top of a
        # synchronised cohort is eligible; a merely strong follower is not.
        theme_ready = (
            support
            & risk_gate
            & group_attack
            & (_num(frame, "group_n") >= 4)
            & (_num(frame, "group_breadth") > 0.15)
            & (_num(frame, "group_up_ratio_2") >= 0.20)
            & (_num(frame, "group_return_median") > 0.005)
            & (_num(frame, "group_amount_median") > 0.70)
            & (_num(frame, "group_relative_return") > 0.003)
            & (leader_rank >= 0.82)
            & (_num(frame, "rank_intraday") >= 0.88)
            & (_num(frame, "group_intraday_rank") >= 0.90)
            & no_chase
        )
        new_theme = (
            theme_ready
            & (_num(frame, "group_prior10_median") < 0.080)
            & (_num(frame, "intraday_return") > 0.018)
            & (_num(frame, "intraday_return") < 0.085)
            & (_num(frame, "from_open") > 0.006)
            & (_num(frame, "amount_ratio_asof") > 0.95)
            & ((ctx["event_evidence"]) | (_num(frame, "group_prior10_median") > 0.010))
        )
        old_leader = (
            theme_ready
            & (_num(frame, "prior_ret10") > 0.045)
            & (ctx["prior_board_evidence"] | (_num(frame, "prior_ret10") > 0.060))
            & (_num(frame, "group_prior10_median") > 0.025)
            & (_num(frame, "group_relative_return") > 0.006)
            & (_num(frame, "intraday_return") > 0.012)
        )
        leader_switch = (
            theme_ready
            & (_num(frame, "group_prior10_rank") <= 0.75)
            & (_num(frame, "intraday_return") > 0.018)
            & (_num(frame, "amount_ratio_asof") > 1.05)
        )
        trigger = active & amount_ok & (new_theme | old_leader | leader_switch)
        mode = pd.Series(
            np.select(
                [new_theme, old_leader, leader_switch],
                ["new_theme_leader", "main_theme_leader", "leader_switch_confirmation"],
                default="no_trade",
            ),
            index=frame.index,
            dtype=object,
        )
        reason = pd.Series(
            np.select(
                [new_theme, old_leader, leader_switch],
                [
                    "增强：新热点有板块扩散，候选在同一信息集内排名第一",
                    "增强：主流题材延续，龙头相对强度和量能同时确认",
                    "增强：板块内强弱切换完成确认，只取新龙头不取跟风",
                ],
                default="NO_TRADE",
            ),
            index=frame.index,
            dtype=object,
        )
        invalidation = pd.Series(
            "板块扩散停止、龙头退居跟风、量能失真或市场进入退潮",
            index=frame.index,
            dtype=object,
        )
        score = (
            0.30 * _num(frame, "group_intraday_rank", 0.0)
            + 0.25 * _num(frame, "rank_intraday", 0.0)
            + 0.18 * leader_rank
            + 0.15 * _num(frame, "group_breadth", 0.0).add(1.0).div(2.0).clip(0.0, 1.0)
            + 0.12 * _amount_quality(_num(frame, "amount_ratio_asof"))
        )

    else:  # lenghuchong
        # Board execution: do not treat an already sealed board as a fillable
        # buy.  Prefer an early charge or a re-seal with sector breadth, and
        # explicitly drop the 14:30 lottery window from this proxy.
        board_quality = _num(frame, "prior_event_board_quality")
        board_quality = board_quality.fillna(_num(frame, "board_quality"))
        atmosphere = (
            support
            & risk_gate
            & (board_quality >= 0.35)
            & (_num(frame, "market_down_ratio_2") < 0.30)
        )
        attack = (
            group_attack
            & (_num(frame, "group_intraday_rank") >= 0.70)
            & (_num(frame, "group_relative_return") > -0.003)
        )
        executable_time = frame["clock_bucket"].isin(["morning", "midday", "late"])
        not_lottery = frame["cutoff"].ne("14:30")
        board_charge = (
            frame["board_stage"].isin(["charging", "broken_recover"])
            & (_num(frame, "intraday_return") > 0.022)
            & (_num(frame, "from_open") > 0.015)
            & (_num(frame, "current_high") >= _num(frame, "upper_limit") * 0.995)
            & (_num(frame, "last_bar_high") >= _num(frame, "upper_limit") * 0.995)
            & (_num(frame, "gap_to_upper").between(-0.035, -0.001))
            & (_num(frame, "board_level_proxy") >= 1)
        )
        re_seal = (
            (frame["board_stage"] == "broken_recover")
            & (_num(frame, "recovery_from_low") > 0.010)
            & (_num(frame, "late_momentum_30m") > 0.001)
        )
        trigger = (
            active
            & amount_ok
            & atmosphere
            & attack
            & executable_time
            & not_lottery
            & (board_charge | re_seal)
        )
        mode = pd.Series(
            np.select([re_seal, board_charge], ["re_seal_confirmation", "early_board_charge"], default="no_trade"),
            index=frame.index,
            dtype=object,
        )
        reason = pd.Series(
            np.select(
                [re_seal, board_charge],
                [
                    "增强：炸板回封且板块仍攻击，下一根K线才是可成交确认",
                    "增强：板块扩散+冲板换手，排除封死板与尾盘彩票",
                ],
                default="NO_TRADE",
            ),
            index=frame.index,
            dtype=object,
        )
        invalidation = pd.Series(
            "炸板不回封、板块不跟、市场退潮、尾盘封死导致无法成交",
            index=frame.index,
            dtype=object,
        )
        score = (
            0.28 * (1.0 + _num(frame, "gap_to_upper") / 0.035).clip(0.0, 1.0)
            + 0.22 * _num(frame, "group_intraday_rank", 0.0)
            + 0.18 * _num(frame, "rank_intraday", 0.0)
            + 0.17 * leader_rank
            + 0.15 * _amount_quality(_num(frame, "amount_ratio_asof"))
        )

    score = score.replace([np.inf, -np.inf], np.nan)
    trigger = (trigger & score.notna()).fillna(False).astype(bool)
    score = score.fillna(-np.inf)
    return trigger, score, reason, mode, invalidation


def generate_cross_signals(
    snapshots: dict[tuple[pd.Timestamp, str], pd.DataFrame], top_n: int
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    """Select first trigger per stock/day, then strongest confirmed setups."""

    signals: dict[str, pd.DataFrame] = {}
    count_rows: list[dict[str, Any]] = []
    for style in STYLES:
        parts: list[pd.DataFrame] = []
        for (date, cutoff), frame in sorted(snapshots.items()):
            trigger, score, reason, mode, invalidation = apply_cross_rule(frame, style)
            count_rows.append(
                {
                    "variant": VARIANT,
                    "style": style,
                    "date": str(date.date()),
                    "cutoff": cutoff,
                    "clock_bucket": str(frame["clock_bucket"].iloc[0]),
                    "market_phase": str(frame["market_phase"].iloc[0]),
                    "universe_n": int(len(frame)),
                    "market_breadth": float(frame["market_breadth"].iloc[0]),
                    "market_median_intraday": float(frame["market_median_intraday"].iloc[0]),
                    "limit_up_count": int(frame["limit_up_count"].iloc[0]),
                    "broken_board_count": int(frame["broken_board_count"].iloc[0]),
                    "trigger_count": int(trigger.sum()),
                }
            )
            if not trigger.any():
                continue
            part = frame.loc[trigger].copy()
            part["variant"] = VARIANT
            part["style"] = style
            part["score"] = score.loc[trigger]
            part["reason"] = reason.loc[trigger]
            part["mode"] = mode.loc[trigger]
            part["invalidation"] = invalidation.loc[trigger]
            # Keep the same point-in-time leader score used by the rule in the
            # trade log; it is a derived as-of field, not a future outcome.
            part["leader_rank"] = _cross_context(frame)["leader_rank"].loc[trigger]
            part["signal_time"] = part["signal_datetime"]
            parts.append(part)
        if not parts:
            signals[style] = pd.DataFrame()
            continue
        candidates = pd.concat(parts, ignore_index=True).sort_values(
            ["signal_date", "instrument", "signal_datetime", "score"],
            ascending=[True, True, True, False],
        )
        candidates = candidates.drop_duplicates(["signal_date", "instrument"], keep="first")
        selected_parts: list[pd.DataFrame] = []
        for _, day in candidates.groupby("signal_date", sort=True):
            selected_parts.append(
                day.sort_values(["score", "signal_datetime"], ascending=[False, True]).head(top_n)
            )
        selected = pd.concat(selected_parts, ignore_index=True) if selected_parts else pd.DataFrame()
        signals[style] = selected.sort_values(
            ["signal_date", "signal_datetime", "score"], ascending=[True, True, False]
        ).reset_index(drop=True)
    return signals, count_rows


def _run_signals(
    signals_by_style: dict[str, pd.DataFrame],
    variant: str,
    minutes: pd.DataFrame,
    trading_dates: list[pd.Timestamp],
    config: base.BacktestConfig,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reports: dict[str, Any] = {}
    trade_rows: list[dict[str, Any]] = []
    for style in STYLES:
        signals = base.attach_outcomes(signals_by_style.get(style, pd.DataFrame()), minutes, trading_dates, config)
        reports[style] = v2._style_report_v2(signals, trading_dates)
        if not signals.empty:
            for row in signals.to_dict("records"):
                row["variant"] = variant
                row["style"] = style
                trade_rows.append(row)
    return reports, trade_rows


def _json_safe(value: Any) -> Any:
    return base._json_safe(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cross-enhanced replay of four public short-term styles")
    parser.add_argument("--start", default=base.BacktestConfig.start)
    parser.add_argument("--end", default=base.BacktestConfig.end)
    parser.add_argument("--top-n", type=int, default=base.BacktestConfig.top_n)
    parser.add_argument("--min-history-days", type=int, default=base.BacktestConfig.min_history_days)
    parser.add_argument("--min-daily-bars", type=int, default=base.BacktestConfig.min_daily_bars)
    parser.add_argument("--signal-times", default=base.BacktestConfig.signal_times)
    parser.add_argument("--max-files", type=int, default=base.BacktestConfig.max_files)
    parser.add_argument("--universe", choices=["cached", "csi800_start"], default=base.BacktestConfig.universe)
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_DIR / "four_experts_cross_enhanced_latest.json"
    )
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    config = base.BacktestConfig(
        start=args.start,
        end=args.end,
        top_n=max(1, args.top_n),
        min_history_days=max(3, args.min_history_days),
        min_daily_bars=max(20, args.min_daily_bars),
        signal_times=args.signal_times,
        max_files=max(0, args.max_files),
        universe=args.universe,
    )
    requested_start = base._date(config.start)
    requested_end = base._date(config.end) if config.end else pd.Timestamp("2100-01-01")
    universe_filter = base.csi800_members_asof(requested_start) if config.universe == "csi800_start" else None
    minutes = base.load_minutes(requested_start, requested_end, config.max_files, universe_filter)
    daily = base.build_daily_features(minutes, config.min_daily_bars)
    if daily.empty:
        raise ValueError("No completed daily rows")
    prior_daily = v2.build_prior_stock_features(daily)
    prior_market = v2.build_prior_market_features(daily)
    event_summary = base.load_event_summary()
    event_history = v2.load_event_history()
    index_daily = v2.load_index_daily_features()
    actual_last = pd.Timestamp(daily["date"].max())
    end = min(requested_end, actual_last)
    signal_times = [item.strip() for item in config.signal_times.split(",") if item.strip()]
    snapshots, signal_dates = base.build_snapshots(
        minutes, daily, requested_start, end, signal_times, event_summary
    )
    if len(signal_dates) <= config.min_history_days:
        raise ValueError(f"Too few completed signal dates: {len(signal_dates)}")
    industry_cache: dict[str, Any] = {}
    event_cache: dict[str, Any] = {}
    snapshots = {
        key: v2.enrich_snapshot(
            value,
            key[0],
            prior_daily,
            prior_market,
            industry_cache,
            event_history,
            event_cache,
            index_daily,
        )
        for key, value in snapshots.items()
    }
    trading_dates = sorted(pd.Timestamp(item) for item in daily["date"].drop_duplicates())
    usable_signal_dates = [
        item
        for item in signal_dates
        if item in trading_dates and trading_dates.index(item) + 5 < len(trading_dates)
    ]
    snapshots = {key: value for key, value in snapshots.items() if key[0] in usable_signal_dates}

    # Baseline uses the already-reviewed pure style-specific rules.  It is
    # included in the same file so any gain/loss from the cross-enhancement is
    # visible instead of being compared with a different data slice.
    baseline_signals_all, baseline_counts_all = v2.generate_signals_v2(snapshots, config.top_n)
    baseline_signals = {style: baseline_signals_all.get(style, pd.DataFrame()) for style in STYLES}
    baseline_reports, baseline_trades = _run_signals(
        baseline_signals, "baseline_v2_2", minutes, trading_dates, config
    )
    cross_signals, cross_counts = generate_cross_signals(snapshots, config.top_n)
    cross_reports, cross_trades = _run_signals(
        cross_signals, VARIANT, minutes, trading_dates, config
    )

    all_trades = baseline_trades + cross_trades
    keep = {
        "variant", "style", "instrument", "signal_date", "cutoff", "signal_datetime", "score",
        "reason", "mode", "invalidation", "market_phase", "clock_bucket", "industry_code",
        "industry_source_date", "group_n", "group_breadth", "group_return_median", "group_relative_return",
        "group_attack", "group_intraday_rank", "group_prior10_rank", "leader_rank", "board_level_proxy",
        "board_stage", "market_breadth", "market_median_intraday", "market_money_score", "collective_oversold",
        "collective_stabilizing", "reward_space_proxy", "risk_space_proxy", "reward_risk_proxy", "intraday_return",
        "from_high", "late_momentum_30m", "gap_to_upper", "prior_event_source_date", "prior_event_data_available",
        "prior_event_limit_up_stock", "prior_event_previous_limit_up_stock", "prior_event_broken_board_stock",
        "prior_event_limit_down_stock", "prior_event_board_days", "prior_event_board_count", "prior_event_turnover",
        "prior_event_theme", "prior_event_theme_count_asof", "prior_event_theme_top_share_asof",
        "prior_index_data_available", "prior_index_ret1", "prior_index_ret3", "prior_index_ret5",
        "prior_index_positive_ratio", "index_risk_contraction", "index_supportive", "entry_filled",
        "entry_reason", "entry_datetime", "entry_open", "exit_1d_filled", "exit_1d_reason", "exit_1d_date",
        "return_1d", "exit_2d_filled", "exit_2d_reason", "exit_2d_date", "return_2d", "exit_5d_filled",
        "exit_5d_reason", "exit_5d_date", "return_5d",
    }
    trade_output = [
        {_key: _json_safe(value) for _key, value in row.items() if _key in keep}
        for row in all_trades
    ]
    count_rows = []
    for item in baseline_counts_all:
        if item["style"] in STYLES:
            item = dict(item)
            item["variant"] = "baseline_v2_2"
            count_rows.append(item)
    count_rows.extend(cross_counts)
    count_frame = pd.DataFrame(count_rows)
    latest_market = []
    if not count_frame.empty:
        latest = count_frame.loc[count_frame["date"] == count_frame["date"].max()]
        latest_market = latest.drop_duplicates(["variant", "date", "cutoff"])[
            [
                "variant", "date", "cutoff", "clock_bucket", "market_phase", "universe_n",
                "market_breadth", "market_median_intraday", "limit_up_count", "broken_board_count",
            ]
        ].to_dict("records")
    industry_known = int(sum((frame["industry_code"] != "UNKNOWN").sum() for frame in snapshots.values()))
    industry_total = int(sum(len(frame) for frame in snapshots.values()))
    minute_coverage_ratio = (
        float(minutes["instrument"].nunique() / len(universe_filter))
        if universe_filter is not None and len(universe_filter)
        else None
    )
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": asdict(config),
        "version": "cross_enhanced_v1_prior_plan_current_confirmation",
        "research_question": "Can later public principles improve the same four style proxies without using future information?",
        "source_document": str(Path(r"D:\BaiduNetdiskDownload\48位游资悟道心得语录\48位游资-上册.pdf")),
        "methodology": {
            "signal": "same v2.2 as-of minute panel; prior plan/regime first, current cohort/leader/execution confirmation second",
            "entry": "first five-minute bar strictly after signal timestamp; locked-up/down next bars are unfilled",
            "exit": "same T+1/T+2/T+5 first-bar-open outcomes as baseline; dynamic stop/hold is a separate next iteration",
            "costs": f"open {config.open_cost:.4%}, close {config.close_cost:.4%}",
            "auction": "not available in the local panel; Asking's auction validation is represented only by current early response and is not claimed to be auction data",
            "theme": "Eastmoney prior event themes when available; otherwise CSRC industry is explicitly only a cohort proxy",
            "market_veto": "fear/poor breadth/index contraction veto; oversold transition is the only explicit exception",
            "selection": "first trigger per stock/day, then highest score up to top-N; no later hindsight replacement",
            "styles": {
                "zhiye": "顺势右侧/强势回踩 + 板块同步 + 不在退潮硬做",
                "asking": "预案 + 早盘/尾盘节奏确认 + 不追杀跌",
                "zhao": "主流题材 + 单一龙头排序 + 只取合力最强者",
                "lenghuchong": "板块攻击 + 冲板/回封可成交 + 排除封死和尾盘彩票",
            },
            "later_chapter_inputs": [
                "不动明王：启动位置、开板/封板过程、成交稀疏与量能突变",
                "艾琳歌：规则一致性、右侧买入、亏损严格处理",
                "退学炒股：只做强势人气股主升，连续失败降低风险",
                "独股一箭：强势股第一波破位后的反弹，题材量能要持续均匀",
                "六哥：主流—龙头—节奏，机会/风险预案与不明时放弃",
                "缠中说禅：先有攻击计划，市场行为确认而不是预测",
                "无门问禅：势/热点/仓位/风险四层，弱市低吸硬否决",
                "北京炒家：板块广度、回封/换手、早盘可成交与预先决定退出",
                "灯心人/九二科比/著名刺客：主升优先、情绪周期、龙头而非单纯板套利",
                "林疯狂/御剑飞鱼：低吸围绕主流龙头，退潮/混沌期减少交易或空仓",
            ],
            "no_lookahead": [
                "industry snapshot is selected only from dates <= signal date",
                "prior market and stock fields use completed dates strictly before signal date",
                "current cohort and execution fields use minute bars <= cutoff",
                "outcomes use only bars after the signal and are not inputs to the trigger",
            ],
        },
        "data_quality": {
            "minute_rows": int(len(minutes)),
            "minute_instruments": int(minutes["instrument"].nunique()),
            "minute_start": str(minutes["datetime"].min()),
            "minute_end": str(minutes["datetime"].max()),
            "minute_source_rows": {str(k): int(v) for k, v in minutes["source"].value_counts(dropna=False).items()},
            "minute_source_instruments": {
                str(k): int(v) for k, v in minutes.groupby("source")["instrument"].nunique().items()
            },
            "universe_filter_instruments": int(len(universe_filter)) if universe_filter is not None else None,
            "minute_coverage_ratio_vs_fixed_universe": minute_coverage_ratio,
            "coverage_warning": (
                "Only a partial fixed-universe replay; do not treat returns as CSI800-wide evidence"
                if minute_coverage_ratio is not None and minute_coverage_ratio < 0.80
                else "Diagnostic cached universe; no fixed-universe coverage denominator"
                if minute_coverage_ratio is None
                else None
            ),
            "completed_daily_dates": int(len(trading_dates)),
            "event_summary_dates": int(len(event_summary)) if not event_summary.empty else 0,
            "event_history_dates": int(event_history["event_date"].nunique()) if not event_history.empty else 0,
            "event_history_start": str(event_history["event_date"].min()) if not event_history.empty else None,
            "event_history_end": str(event_history["event_date"].max()) if not event_history.empty else None,
            "index_files": int(len(list(v2.INDEX_DIR.glob("*.parquet")))) if not index_daily.empty else 0,
            "index_dates": int(len(index_daily)) if not index_daily.empty else 0,
            "industry_known_snapshot_rows": industry_known,
            "industry_snapshot_rows": industry_total,
            "industry_row_coverage": float(industry_known / industry_total) if industry_total else 0.0,
            "signal_dates_before_forward_reserve": int(len(signal_dates)),
            "usable_signal_dates": int(len(usable_signal_dates)),
            "usable_signal_start": str(min(usable_signal_dates)) if usable_signal_dates else None,
            "usable_signal_end": str(max(usable_signal_dates)) if usable_signal_dates else None,
        },
        "baseline_v2_2": baseline_reports,
        "cross_enhanced": cross_reports,
        "latest_market_snapshots": _json_safe(latest_market),
        "signal_counts": _json_safe(count_rows),
        "trades": trade_output,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(_json_safe({"baseline_v2_2": baseline_reports, "cross_enhanced": cross_reports}), ensure_ascii=False, indent=2))
    print(f"result: {args.output}")
    return result


if __name__ == "__main__":
    main()
