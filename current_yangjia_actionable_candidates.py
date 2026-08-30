"""Create an actionable next-session watchlist from the Yangjia-style proxy.

The previous ``current_yangjia_candidates.py`` is a close-of-day review table.
That table intentionally contains current limit-up names, but those names are
not executable buys at the time the table is produced.  This module changes the
question:

* signal time is after the latest completed session;
* current-session limit-up stocks are excluded from the primary watchlist;
* candidates must have a measurable leader/main-line footprint and a controlled
  divergence or repair setup;
* every candidate receives a next-session opening-gap range, a confirmation
  trigger, a no-trade rule, and a small initial/confirmation position budget.

This is still only a public-information research proxy.  It does not reproduce
private discretionary information, order-book reading, or the actual trading
record of 炒股养家.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import OUTPUT_DIR, PROJECT_ROOT


@dataclass(frozen=True)
class ActionableConfig:
    input_result: str = ""
    top_n: int = 12
    max_per_industry: int = 3
    initial_position_pct: float = 0.05
    confirmation_position_pct: float = 0.15


def _safe_value(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if not isinstance(value, (list, tuple, dict)) and pd.isna(value):
        return None
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_safe_value), encoding="utf-8"
    )
    temporary.replace(path)


def _number(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def _clip(series: pd.Series, low: float = 0.0, high: float = 1.0) -> pd.Series:
    return series.astype(float).clip(lower=low, upper=high).fillna(0.0)


def _rank01(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() == 0 or numeric.nunique(dropna=True) <= 1:
        return pd.Series(0.0, index=series.index)
    return numeric.rank(pct=True).fillna(0.0)


def _latest_input_path(config: ActionableConfig) -> tuple[Path, dict[str, Any]]:
    if config.input_result:
        result_path = Path(config.input_result)
        payload_path = result_path if result_path.suffix.lower() == ".json" else None
        if payload_path and payload_path.exists():
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        else:
            payload = {}
    else:
        payload_path = OUTPUT_DIR / "current_yangjia_candidates_latest.json"
        if not payload_path.exists():
            raise FileNotFoundError(f"missing close-of-day input: {payload_path}")
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    csv_path = Path(payload.get("artifacts", {}).get("candidate_scores_csv", ""))
    if not csv_path.exists():
        raise FileNotFoundError(f"missing candidate scores CSV: {csv_path}")
    return csv_path, payload


def _load_today_pool(asof: pd.Timestamp, kind: str) -> pd.DataFrame:
    path = PROJECT_ROOT / "data_lake" / "raw" / "eastmoney" / "current" / kind / f"{asof:%Y%m%d}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["code"])
    frame = pd.read_parquet(path)
    if "code" in frame:
        frame["code"] = frame["code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    return frame


def _classify_setup(row: pd.Series) -> str:
    ret1 = float(row["ret_1d"])
    previous = bool(row["previous_limit_up"])
    broken = bool(row["today_broken_stock"])
    recent = float(row["limit_up_count_5d"] + row["limit_up_count_20d"])
    if (previous or broken) and ret1 <= 0.02:
        return "人气核心分歧低吸"
    if (previous or broken) and ret1 > 0.02:
        return "人气核心弱转强预案"
    if recent > 0 and ret1 <= 0.02:
        return "主线受控回撤"
    return "主线试错"


def _entry_plan(setup: str, close: float, config: ActionableConfig) -> dict[str, Any]:
    if setup == "人气核心分歧低吸" or setup == "主线受控回撤":
        gap_low, gap_high, chase = -0.04, 0.02, 0.02
        trigger = "开盘不低于前收-4%，09:30-09:45止跌并重新站回前收/分时均线；只在板块同步转强时试错"
        abort = "低开超过4%、跌破前一日低点，或板块核心继续走弱：放弃"
    elif setup == "人气核心弱转强预案":
        gap_low, gap_high, chase = -0.01, 0.05, 0.05
        trigger = "竞价接近前收且开盘后15分钟不破开盘价，个股与主线同步放量转强后再试错"
        abort = "竞价低于前收1%以上、开盘即跌破开盘价，或高开超过5%：放弃追价"
    else:
        gap_low, gap_high, chase = -0.03, 0.03, 0.03
        trigger = "开盘后出现主动买盘并突破早盘高点，且所属行业至少有一只核心股同步走强"
        abort = "没有板块联动或开盘后量价走弱：不交易"
    return {
        "entry_gap_low_pct": gap_low,
        "entry_gap_high_pct": gap_high,
        "max_chase_gap_pct": chase,
        "reference_entry_low": close * (1.0 + gap_low) if close > 0 else np.nan,
        "reference_entry_high": close * (1.0 + gap_high) if close > 0 else np.nan,
        "risk_stop_reference": close * 0.94 if close > 0 else np.nan,
        "trigger": trigger,
        "abort_rule": abort,
    }


def _score_actionable(frame: pd.DataFrame, market: dict[str, Any], config: ActionableConfig) -> pd.DataFrame:
    result = frame.copy()
    for column in (
        "current_limit_up",
        "previous_limit_up",
        "limit_up_count_5d",
        "limit_up_count_20d",
        "max_board_days",
        "lhb_count",
        "lhb_net_ratio_mean_pct",
        "lhb_latest_net_ratio_pct",
        "industry_heat_5d",
        "ret_1d",
        "ret_5d",
        "ret_20d",
        "drawdown_20d",
        "daily_amount_ratio_5d",
        "current_broken_count",
    ):
        if column not in result:
            result[column] = 0.0
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0.0)

    result["is_st"] = result.get("name", pd.Series("", index=result.index)).astype(str).str.contains(
        r"ST|退", case=False, regex=True
    )

    # Today’s broken-board pool is a true divergence input.  A stock that
    # already closed at limit-up is explicitly not an actionable primary setup.
    result["today_broken_stock"] = result.get("today_broken_stock", 0).astype(bool)
    result["current_limit_up"] = result["current_limit_up"].astype(bool)

    leader = (
        0.35 * _clip(result["limit_up_count_20d"] / 4.0)
        + 0.25 * _clip(result["max_board_days"] / 4.0)
        + 0.25 * _rank01(result["industry_heat_5d"])
        + 0.15 * _clip(result["lhb_count"] / 3.0)
    )
    trend = 0.55 * _clip((result["ret_20d"] + 0.05) / 0.35) + 0.45 * _clip(
        (result["ret_5d"] + 0.02) / 0.22
    )
    # Peak score around a controlled -3% daily pullback.  A limit-down-like
    # collapse or an unchanged/strong consensus close scores lower.
    controlled_pullback = _clip(1.0 - (result["ret_1d"] + 0.03).abs() / 0.05)
    repair = controlled_pullback * (0.65 * trend + 0.35 * _clip(result["drawdown_20d"] / -0.25 + 1.0))
    weak_to_strong = _clip(
        0.55 * result["previous_limit_up"].astype(float)
        + 0.35 * result["today_broken_stock"].astype(float)
        + 0.10 * _clip(result["limit_up_count_5d"] / 2.0)
    )
    asof = pd.Timestamp(market.get("asof_date", pd.Timestamp.today())).normalize()
    if "lhb_latest_date" in result:
        latest_date = pd.to_datetime(result["lhb_latest_date"], errors="coerce").dt.normalize()
    else:
        latest_date = pd.Series(pd.NaT, index=result.index, dtype="datetime64[ns]")
    lhb_age = (asof - latest_date).dt.days.fillna(99).clip(lower=0)
    lhb_recency = np.exp(-lhb_age / 5.0)
    latest_ratio = result["lhb_latest_net_ratio_pct"]
    capital_direction = 0.65 * _clip((latest_ratio + 1.0) / 5.0) + 0.35 * _clip(
        (result["lhb_net_ratio_mean_pct"] + 1.0) / 5.0
    )
    capital = _clip(result["lhb_count"] / 3.0) * (0.55 + 0.45 * lhb_recency) * capital_direction
    # Adequate turnover is useful, but an extreme one-day volume burst on a
    # divergence close is more often exhaustion than confirmation.
    liquidity = _clip((result["daily_amount_ratio_5d"] - 0.5) / 2.0)

    overheat = _clip((result["ret_20d"] - 0.45) / 0.35)
    collapse = _clip((-result["ret_1d"] - 0.08) / 0.10)
    broken_risk = _clip(result["current_broken_count"] / 4.0)
    negative_capital = _clip(-latest_ratio / 5.0)
    volume_exhaustion = _clip((result["daily_amount_ratio_5d"] - 3.0) / 8.0)
    risk = (
        18 * overheat
        + 16 * collapse
        + 12 * broken_risk
        + 8 * negative_capital
        + 10 * volume_exhaustion
    )

    result["mainline_score"] = 28 * leader
    result["divergence_score"] = 25 * repair + 12 * weak_to_strong
    result["confirmation_score"] = 15 * trend + 8 * capital + 5 * liquidity
    result["risk_penalty"] = risk
    result["score"] = (
        result["mainline_score"]
        + result["divergence_score"]
        + result["confirmation_score"]
        - result["risk_penalty"]
    ).clip(-20, 100)

    # A low-risk divergence setup still needs a living trend and a living
    # main line.  This prevents the common mistake of calling every falling
    # stock a "low吸" opportunity merely because it was once strong.
    result["trend_supported"] = (result["ret_5d"] >= -0.03) & (result["ret_20d"] > 0)
    result["mainline_supported"] = result["industry_heat_5d"] >= 4
    recent_lhb = result["lhb_count"] > 0
    latest_capital_ok = (~recent_lhb) | (latest_ratio >= -1.0) | (lhb_age > 5)
    result["capital_supported"] = latest_capital_ok
    result["candidate_ready"] = (
        result["trend_supported"]
        & result["mainline_supported"]
        & (result["ret_1d"] >= -0.06)
        & result["capital_supported"]
    )

    # Hard exclusions are applied after scoring so the audit can explain why
    # a name disappeared from the executable list.
    result["exclusion_reason"] = ""
    result.loc[result["current_limit_up"], "exclusion_reason"] = "当日已收涨停：不作为次日无条件买入"
    result.loc[result["is_st"], "exclusion_reason"] = "ST/退市风险"
    result.loc[result["today_limit_down"], "exclusion_reason"] = "当日跌停"
    result.loc[~result["trend_supported"], "exclusion_reason"] = "近5日趋势走坏：不是受控分歧"
    result.loc[~result["mainline_supported"], "exclusion_reason"] = "主线近5日联动不足"
    result.loc[~result["capital_supported"], "exclusion_reason"] = "龙虎榜净买入结构偏弱"
    result.loc[result["ret_1d"] < -0.06, "exclusion_reason"] = "当日回撤过深：不做下跌刀"
    result.loc[result["score"] < 35, "exclusion_reason"] = "分歧质量/趋势确认不足"

    result["setup"] = result.apply(_classify_setup, axis=1)
    plans = result.apply(lambda row: _entry_plan(row["setup"], float(row.get("close", np.nan)), config), axis=1)
    plan_frame = pd.DataFrame(list(plans), index=result.index)
    result = pd.concat([result, plan_frame], axis=1)
    regime = str(market.get("market_regime_proxy", "中性"))
    if "偏强" in regime:
        result["initial_position_pct"] = config.initial_position_pct
        result["confirmation_position_pct"] = config.confirmation_position_pct
    else:
        result["initial_position_pct"] = min(config.initial_position_pct, 0.03)
        result["confirmation_position_pct"] = min(config.confirmation_position_pct, 0.08)
    result["position_rule"] = "先试错仓；触发确认条件才允许加仓；条件失效直接退出，不补仓摊平"
    result["rank"] = result["score"].rank(method="first", ascending=False).astype(int)
    return result.sort_values("score", ascending=False).reset_index(drop=True)


def _select_diversified(result: pd.DataFrame, config: ActionableConfig) -> pd.DataFrame:
    eligible = result.loc[
        (result["score"] >= 35)
        & (result["candidate_ready"])
        & (~result["current_limit_up"])
        & (~result["today_limit_down"])
        & (~result["is_st"])
    ].copy()
    selected: list[int] = []
    industry_counts: dict[str, int] = {}
    for index, row in eligible.iterrows():
        industry = str(row.get("industry", "未知")) or "未知"
        if industry_counts.get(industry, 0) >= config.max_per_industry:
            continue
        selected.append(index)
        industry_counts[industry] = industry_counts.get(industry, 0) + 1
        if len(selected) >= config.top_n:
            break
    return eligible.loc[selected].copy() if selected else eligible.head(0)


def _write_validation_template(frame: pd.DataFrame, path: Path) -> None:
    columns = [
        "asof_date",
        "rank",
        "instrument",
        "code",
        "name",
        "setup",
        "score",
        "close",
        "reference_entry_low",
        "reference_entry_high",
        "entry_gap_low_pct",
        "entry_gap_high_pct",
        "max_chase_gap_pct",
        "trigger",
        "abort_rule",
        "initial_position_pct",
        "confirmation_position_pct",
        "next_open",
        "first_15m_high",
        "first_15m_low",
        "executed",
        "entry_price_actual",
        "forward_1d_return",
        "forward_3d_return",
        "forward_5d_return",
        "notes",
    ]
    output = frame.copy()
    for column in columns:
        if column not in output:
            output[column] = np.nan
    output["next_open"] = np.nan
    output["first_15m_high"] = np.nan
    output["first_15m_low"] = np.nan
    output["executed"] = ""
    output["entry_price_actual"] = np.nan
    for column in ("forward_1d_return", "forward_3d_return", "forward_5d_return"):
        output[column] = np.nan
    output["notes"] = "只在 trigger 满足时记录 executed=1；否则记录 0，不把未触发信号算成亏损"
    output[columns].to_csv(path, index=False, encoding="utf-8-sig")


def run(config: ActionableConfig) -> dict[str, Any]:
    csv_path, close_payload = _latest_input_path(config)
    scores = pd.read_csv(csv_path, encoding="utf-8-sig")
    summary = close_payload.get("market_summary", {})
    asof = pd.Timestamp(summary.get("asof_date", close_payload.get("asof_date"))).normalize()
    today_broken = _load_today_pool(asof, "broken_board_pool")
    today_limit_down = _load_today_pool(asof, "limit_down_pool")
    if "code" not in today_broken:
        today_broken["code"] = pd.Series(dtype=str)
    if "code" not in today_limit_down:
        today_limit_down["code"] = pd.Series(dtype=str)
    broken_codes = set(today_broken["code"].astype(str))
    down_codes = set(today_limit_down["code"].astype(str))

    scores["code"] = scores["code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    scores["today_broken_stock"] = scores["code"].isin(broken_codes)
    scores["today_limit_down"] = scores["code"].isin(down_codes)
    scored = _score_actionable(scores, summary, config)
    selected = _select_diversified(scored, config)
    selected["asof_date"] = asof
    selected["instrument"] = selected["instrument"].astype(str)
    selected["knowledge_time"] = asof

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_DIR / "current_yangjia_actionable" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    output_columns = [
        "rank",
        "instrument",
        "code",
        "name",
        "setup",
        "score",
        "mainline_score",
        "divergence_score",
        "confirmation_score",
        "risk_penalty",
        "industry",
        "industry_heat_5d",
        "current_limit_up",
        "today_broken_stock",
        "today_limit_down",
        "trend_supported",
        "mainline_supported",
        "capital_supported",
        "candidate_ready",
        "previous_limit_up",
        "limit_up_count_5d",
        "limit_up_count_20d",
        "max_board_days",
        "lhb_count",
        "lhb_net_ratio_mean_pct",
        "lhb_latest_net",
        "lhb_latest_net_ratio_pct",
        "lhb_latest_date",
        "ret_1d",
        "ret_5d",
        "ret_20d",
        "drawdown_20d",
        "daily_amount_ratio_5d",
        "close",
        "reference_entry_low",
        "reference_entry_high",
        "entry_gap_low_pct",
        "entry_gap_high_pct",
        "max_chase_gap_pct",
        "risk_stop_reference",
        "initial_position_pct",
        "confirmation_position_pct",
        "trigger",
        "abort_rule",
        "position_rule",
        "source_event",
        "source_daily",
        "knowledge_time",
    ]
    for column in output_columns:
        if column not in selected:
            selected[column] = np.nan
    selected[output_columns].to_csv(output_dir / "actionable_watchlist.csv", index=False, encoding="utf-8-sig")
    _write_validation_template(selected, output_dir / "actionable_validation_template.csv")

    excluded_summary = (
        scored.loc[scored["exclusion_reason"].astype(str) != "", "exclusion_reason"]
        .value_counts()
        .to_dict()
    )
    plan = {
        "asof_date": asof,
        "actionable_definition": "当前收盘后生成、次日竞价和开盘确认执行；当日收涨停不进入主候选",
        "market_regime_proxy": summary.get("market_regime_proxy", "未知"),
        "input_close_of_day_scores": str(csv_path),
        "primary_watchlist_count": int(len(selected)),
        "primary_current_limit_up_count": int(selected["current_limit_up"].sum()) if not selected.empty else 0,
        "excluded_summary": excluded_summary,
        "rules": {
            "anticipate": "预判只用小仓位试错，不因单只股票分数高直接重仓",
            "confirm": "次日竞价/前15分钟满足 trigger，且主线同步转强，才允许加仓",
            "sell_risk": "跌破 abort_rule 或失去板块联动，退出；不补仓摊平",
            "consensus": "高开超过 max_chase_gap_pct 不追，避免把一致性当买点",
        },
        "top_candidates": json.loads(
            selected[output_columns].to_json(orient="records", force_ascii=False, date_format="iso")
        ),
        "artifacts": {
            "actionable_watchlist": str(output_dir / "actionable_watchlist.csv"),
            "validation_template": str(output_dir / "actionable_validation_template.csv"),
            "close_of_day_input": str(csv_path),
        },
    }
    _write_json(output_dir / "actionable_plan.json", plan)
    _write_json(OUTPUT_DIR / "current_yangjia_actionable_latest.json", plan)

    print(
        f"asof={asof:%Y-%m-%d} primary={len(selected)} "
        f"current_limit_up_in_primary={int(selected['current_limit_up'].sum()) if not selected.empty else 0}"
    )
    for _, row in selected.iterrows():
        print(
            f"{int(row['rank']):>2} {row['instrument']:<8} {str(row.get('name', '')):<8} "
            f"score={row['score']:>6.2f} {row['setup']} "
            f"gap={row['entry_gap_low_pct']:.0%}..{row['entry_gap_high_pct']:.0%} "
            f"行业={row.get('industry', '')}"
        )
    print(f"output={output_dir}")
    return plan


def parse_args() -> ActionableConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-result", default="")
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--max-per-industry", type=int, default=3)
    parser.add_argument("--initial-position-pct", type=float, default=0.05)
    parser.add_argument("--confirmation-position-pct", type=float, default=0.15)
    args = parser.parse_args()
    return ActionableConfig(
        input_result=args.input_result,
        top_n=max(1, args.top_n),
        max_per_industry=max(1, args.max_per_industry),
        initial_position_pct=max(0.0, min(1.0, args.initial_position_pct)),
        confirmation_position_pct=max(0.0, min(1.0, args.confirmation_position_pct)),
    )


if __name__ == "__main__":
    run(parse_args())
