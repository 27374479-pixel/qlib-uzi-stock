"""Auditable, recall-first candidate factory for the UZI research pipeline.

The factory deliberately separates discovery from final stock judgment:

* one or more quantitative sources contribute broad recall candidates;
* four evidence pools can add candidates when their point-in-time fields exist;
* a quality gate records vetoes and missing evidence instead of filling defaults;
* the result is routed into UZI lite / medium / deep research queues.

The module is usable today with existing ``base_candidates_*.json`` files.  In
that mode only the quantitative recall source is active and the report says so
explicitly.  Financial and catalyst pools activate only after an exact-date
feature snapshot is supplied.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from config import OUTPUT_DIR


@dataclass(frozen=True)
class FactoryConfig:
    source_quota: int = 30
    pool_quota: int = 15
    lite_n: int = 20
    medium_n: int = 8
    deep_n: int = 3
    min_pool_coverage: float = 0.20
    min_common_data_confidence: float = 0.55


@dataclass(frozen=True)
class PoolSpec:
    label: str
    required: tuple[str, ...]
    scorer: Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]]


COMMON_AUDIT_FIELDS = (
    "close",
    "amount_20",
    "trade_status",
    "is_st",
    "pe_ttm",
    "pb_mrq",
    "revenue_growth_yoy",
    "profit_growth_yoy",
    "cashflow_to_profit",
    "nonrecurring_profit_share",
    "debt_ratio",
)


def normalize_instrument(value: str) -> str:
    text = str(value).strip().upper()
    if text.isdigit() and len(text) < 6:
        text = text.zfill(6)
    if text.endswith((".SH", ".SZ")):
        code, market = text.split(".")
        return f"{market}{code}"
    if text.startswith(("SH", "SZ")) and len(text) == 8:
        return text
    if text.isdigit() and len(text) == 6:
        return ("SH" if text.startswith(("6", "9")) else "SZ") + text
    raise ValueError(f"Unsupported A-share instrument: {value!r}")


def uzi_ticker(instrument: str) -> str:
    normalized = normalize_instrument(instrument)
    return f"{normalized[2:]}.{normalized[:2]}"


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan)


def _rank(values: pd.Series, higher: bool = True) -> pd.Series:
    return values.rank(pct=True, ascending=higher)


def _weighted_rank(frame: pd.DataFrame, weights: dict[str, tuple[float, bool]]) -> pd.Series:
    numerator = pd.Series(0.0, index=frame.index)
    denominator = pd.Series(0.0, index=frame.index)
    for column, (weight, higher) in weights.items():
        ranked = _rank(_numeric(frame, column), higher=higher)
        present = ranked.notna()
        numerator = numerator.add(ranked.fillna(0.0) * weight)
        denominator = denominator.add(present.astype(float) * weight)
    return numerator.div(denominator.where(denominator > 0))


def _earnings_score(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    eligible = (
        (_numeric(frame, "revenue_growth_yoy") >= 0.15)
        & (_numeric(frame, "profit_growth_yoy") >= 0.30)
        & (_numeric(frame, "cashflow_to_profit") >= 0.50)
        & (_numeric(frame, "nonrecurring_profit_share") <= 0.30)
        & (_numeric(frame, "pe_ttm") > 0)
    )
    score = _weighted_rank(
        frame,
        {
            "profit_growth_yoy": (0.30, True),
            "revenue_growth_yoy": (0.20, True),
            "cashflow_to_profit": (0.20, True),
            "gross_margin_yoy_delta": (0.10, True),
            "pe_ttm": (0.20, False),
        },
    )
    return eligible, score


def _cycle_score(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    eligible = (
        (_numeric(frame, "gross_margin_qoq_delta") > 0)
        & (_numeric(frame, "capacity_utilization_qoq_delta") > 0)
        & _numeric(frame, "ret20").between(-0.15, 0.35)
        & (_numeric(frame, "pb_mrq") > 0)
    )
    score = _weighted_rank(
        frame,
        {
            "gross_margin_qoq_delta": (0.30, True),
            "capacity_utilization_qoq_delta": (0.30, True),
            "product_price_change": (0.15, True),
            "inventory_growth_delta": (0.10, False),
            "pb_mrq": (0.15, False),
        },
    )
    return eligible, score


def _quality_pullback_score(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    eligible = (
        (_numeric(frame, "roe_ttm") >= 0.10)
        & (_numeric(frame, "cashflow_to_profit") >= 0.80)
        & (_numeric(frame, "debt_ratio") <= 0.70)
        & _numeric(frame, "drawdown_120").between(-0.40, -0.10)
        & (_numeric(frame, "pe_quantile_5y") <= 0.60)
    )
    score = _weighted_rank(
        frame,
        {
            "roe_ttm": (0.25, True),
            "cashflow_to_profit": (0.25, True),
            "debt_ratio": (0.15, False),
            "pe_quantile_5y": (0.20, False),
            "drawdown_120": (0.15, False),
        },
    )
    return eligible, score


def _catalyst_score(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    eligible = (
        (_numeric(frame, "catalyst_score") >= 0.50)
        & (_numeric(frame, "earnings_revision_3m") >= 0)
        & (_numeric(frame, "relative_strength_60") >= 0.50)
        & (_numeric(frame, "ret20") <= 0.35)
        & (_numeric(frame, "dist_ma20") <= 0.20)
    )
    score = _weighted_rank(
        frame,
        {
            "catalyst_score": (0.35, True),
            "earnings_revision_3m": (0.25, True),
            "relative_strength_60": (0.20, True),
            "ret20": (0.10, True),
            "dist_ma20": (0.10, False),
        },
    )
    return eligible, score


POOL_SPECS = {
    "earnings_inflection": PoolSpec(
        "业绩拐点",
        (
            "revenue_growth_yoy",
            "profit_growth_yoy",
            "cashflow_to_profit",
            "nonrecurring_profit_share",
            "pe_ttm",
        ),
        _earnings_score,
    ),
    "cycle_reversal": PoolSpec(
        "周期反转",
        ("gross_margin_qoq_delta", "capacity_utilization_qoq_delta", "ret20", "pb_mrq"),
        _cycle_score,
    ),
    "quality_pullback": PoolSpec(
        "质量回调",
        ("roe_ttm", "cashflow_to_profit", "debt_ratio", "drawdown_120", "pe_quantile_5y"),
        _quality_pullback_score,
    ),
    "industry_catalyst": PoolSpec(
        "产业催化",
        ("catalyst_score", "earnings_revision_3m", "relative_strength_60", "ret20", "dist_ma20"),
        _catalyst_score,
    ),
}


def audit_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach explicit data confidence, veto reasons and warnings."""

    result = frame.copy()
    available = pd.DataFrame(
        {column: _numeric(result, column).notna() for column in COMMON_AUDIT_FIELDS},
        index=result.index,
    )
    result["data_confidence"] = available.mean(axis=1)
    if "trusted_pre_filter" in result:
        trusted = result["trusted_pre_filter"].fillna(False).astype(bool)
        result.loc[trusted, "data_confidence"] = result.loc[trusted, "data_confidence"].clip(lower=0.45)

    vetoes: list[list[str]] = []
    warnings: list[list[str]] = []
    for instrument, row in result.iterrows():
        veto: list[str] = []
        warning: list[str] = []
        if pd.notna(row.get("trade_status")) and int(row["trade_status"]) != 1:
            veto.append("停牌或不可交易")
        if pd.notna(row.get("is_st")) and int(row["is_st"]) != 0:
            veto.append("ST风险")
        if pd.notna(row.get("close")) and float(row["close"]) < 2.0:
            veto.append("股价低于流动性安全线")
        if pd.notna(row.get("amount_20")) and float(row["amount_20"]) < 50_000_000:
            veto.append("20日平均成交额低于5000万元")
        if pd.notna(row.get("nonrecurring_profit_share")) and float(row["nonrecurring_profit_share"]) > 0.30:
            veto.append("非经常损益占比超过30%")
        if pd.notna(row.get("cashflow_to_profit")) and float(row["cashflow_to_profit"]) < 0.50:
            veto.append("经营现金流/净利润低于0.5")
        revenue_growth = row.get("revenue_growth_yoy")
        receivable_growth = row.get("receivables_growth_yoy")
        inventory_growth = row.get("inventory_growth_yoy")
        if pd.notna(revenue_growth) and pd.notna(receivable_growth) and receivable_growth > revenue_growth + 0.20:
            veto.append("应收增速高于收入20个百分点")
        if pd.notna(revenue_growth) and pd.notna(inventory_growth) and inventory_growth > revenue_growth + 0.20:
            veto.append("存货增速高于收入20个百分点")
        missing = [column for column in COMMON_AUDIT_FIELDS if pd.isna(row.get(column))]
        if missing:
            warning.append("缺失审计字段: " + ",".join(missing))
        vetoes.append(veto)
        warnings.append(warning)
    result["veto_reasons"] = vetoes
    result["warnings"] = warnings
    result["hard_veto"] = result["veto_reasons"].map(bool)
    return result


def _pool_candidates(
    audited: pd.DataFrame,
    config: FactoryConfig,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selections: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}
    for pool_id, spec in POOL_SPECS.items():
        required_present = audited.reindex(columns=spec.required).notna().all(axis=1)
        coverage = float(required_present.mean()) if len(audited) else 0.0
        active = coverage >= config.min_pool_coverage
        diagnostic = {
            "label": spec.label,
            "active": active,
            "coverage": coverage,
            "required": list(spec.required),
            "reason": None if active else "point-in-time fields do not meet coverage threshold",
        }
        if not active:
            diagnostics[pool_id] = diagnostic
            continue
        eligible, scores = spec.scorer(audited)
        usable = eligible & required_present & ~audited["hard_veto"] & scores.notna()
        chosen = scores.loc[usable].sort_values(ascending=False).head(config.pool_quota)
        diagnostic["eligible_count"] = int(usable.sum())
        diagnostic["selected_count"] = int(len(chosen))
        diagnostics[pool_id] = diagnostic
        for instrument, score in chosen.items():
            selections.append(
                {
                    "instrument": instrument,
                    "source": pool_id,
                    "source_label": spec.label,
                    "source_score": float(score),
                    "evidence_pool": True,
                }
            )
    return selections, diagnostics


def _quant_candidates(recall: pd.DataFrame, config: FactoryConfig) -> list[dict[str, Any]]:
    selections: list[dict[str, Any]] = []
    if recall.empty:
        return selections
    for source, group in recall.groupby("source", sort=True):
        selected = group.sort_values(["source_score", "source_rank"], ascending=[False, True]).head(config.source_quota)
        for _, row in selected.iterrows():
            selections.append(
                {
                    "instrument": row["instrument"],
                    "source": source,
                    "source_label": source,
                    "source_score": float(row["source_score"]),
                    "evidence_pool": False,
                }
            )
    return selections


def build_factory(
    snapshot: pd.DataFrame,
    recall_candidates: pd.DataFrame,
    config: FactoryConfig = FactoryConfig(),
) -> dict[str, Any]:
    """Build an auditable candidate union and UZI research queues."""

    frame = snapshot.copy()
    frame.index = pd.Index([normalize_instrument(item) for item in frame.index], name="instrument")
    frame = frame[~frame.index.duplicated(keep="last")]
    audited = audit_snapshot(frame)
    quant = _quant_candidates(recall_candidates, config)
    pool, diagnostics = _pool_candidates(audited, config)
    selections = quant + pool

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in selections:
        grouped.setdefault(item["instrument"], []).append(item)

    records = []
    for instrument, sources in grouped.items():
        if instrument not in audited.index:
            continue
        audit = audited.loc[instrument]
        source_scores = [float(item["source_score"]) for item in sources]
        evidence_count = sum(bool(item["evidence_pool"]) for item in sources)
        source_count = len({item["source"] for item in sources})
        priority = (
            0.45 * max(source_scores)
            + 0.25 * float(np.mean(source_scores))
            + 0.15 * min(source_count / 3.0, 1.0)
            + 0.15 * float(audit["data_confidence"])
        )
        records.append(
            {
                "instrument": instrument,
                "ticker": uzi_ticker(instrument),
                "priority_score": priority,
                "source_count": source_count,
                "evidence_pool_count": evidence_count,
                "sources": [item["source"] for item in sources],
                "source_labels": [item["source_label"] for item in sources],
                "data_confidence": float(audit["data_confidence"]),
                "hard_veto": bool(audit["hard_veto"]),
                "veto_reasons": list(audit["veto_reasons"]),
                "warnings": list(audit["warnings"]),
            }
        )
    records.sort(
        key=lambda item: (item["hard_veto"], -item["source_count"], -item["priority_score"])
    )
    for rank, item in enumerate(records, 1):
        item["rank"] = rank

    usable = [item for item in records if not item["hard_veto"]]
    lite = usable[: config.lite_n]
    medium = [
        item
        for item in lite
        if item["data_confidence"] >= config.min_common_data_confidence
        or item["evidence_pool_count"] >= 1
        or item["source_count"] >= 2
    ][: config.medium_n]
    deep = [
        item
        for item in medium
        if item["data_confidence"] >= 0.70 and item["evidence_pool_count"] >= 1
    ][: config.deep_n]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": asdict(config),
        "methodology": {
            "objective": "high-recall discovery followed by evidence and data-quality gates",
            "uzi_role": "research routing, veto, valuation and invalidation; not raw discovery score",
            "missing_data_policy": "do not impute; deactivate evidence pool and report coverage",
        },
        "pool_diagnostics": diagnostics,
        "counts": {
            "snapshot": int(len(audited)),
            "union": int(len(records)),
            "vetoed": int(sum(item["hard_veto"] for item in records)),
            "lite": len(lite),
            "medium": len(medium),
            "deep": len(deep),
        },
        "candidates": records,
        "uzi_queues": {
            "lite": [item["ticker"] for item in lite],
            "medium": [item["ticker"] for item in medium],
            "deep": [item["ticker"] for item in deep],
        },
    }


def load_recall_source(path: Path, source: str) -> pd.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("candidates", payload.get("picks", payload if isinstance(payload, list) else []))
    if not isinstance(rows, list):
        raise ValueError(f"{path} does not contain a candidate list")
    records = []
    total = max(len(rows), 1)
    for position, row in enumerate(rows, 1):
        raw_instrument = row.get("instrument") or row.get("ticker") or row.get("code")
        if not raw_instrument:
            continue
        rank = int(row.get("rank") or position)
        raw_score = row.get("leader_score", row.get("score"))
        score = float(raw_score) if raw_score is not None else 1.0 - (rank - 1) / total
        records.append(
            {
                "instrument": normalize_instrument(raw_instrument),
                "source": source,
                "source_score": score,
                "source_rank": rank,
                "trusted_pre_filter": True,
                **{key: value for key, value in row.items() if key not in {"instrument", "ticker", "code"}},
            }
        )
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    frame["source_score"] = frame.groupby("source")["source_score"].rank(pct=True)
    return frame


def load_feature_snapshot(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        frame = pd.read_parquet(path)
    elif suffix == ".csv":
        # Reading all columns as text preserves leading zeroes in Shenzhen
        # stock codes. Numeric feature coercion happens only inside scorers.
        frame = pd.read_csv(path, dtype=str)
    elif suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        frame = pd.DataFrame(payload.get("records", payload))
    else:
        raise ValueError(f"Unsupported snapshot format: {path.suffix}")
    instrument_column = next((column for column in ("instrument", "ticker", "code") if column in frame), None)
    if instrument_column is None:
        raise ValueError("Feature snapshot needs instrument, ticker or code")
    frame["instrument"] = frame[instrument_column].map(normalize_instrument)
    return frame.set_index("instrument")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else float(value)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build recall-first UZI candidate queues")
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        metavar="NAME=JSON",
        help="repeatable quantitative candidate source",
    )
    parser.add_argument("--features", type=Path, help="optional exact-date feature snapshot")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> dict[str, Any]:
    args = parse_args()
    parts = []
    for source_arg in args.source:
        if "=" not in source_arg:
            raise ValueError("--source must be NAME=JSON")
        name, raw_path = source_arg.split("=", 1)
        parts.append(load_recall_source(Path(raw_path), name))
    recall = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if args.features:
        snapshot = load_feature_snapshot(args.features)
    else:
        snapshot = recall.drop_duplicates("instrument").set_index("instrument")
    # Preserve the strongest trusted-pre-filter flag when a separate feature
    # snapshot is joined to recall sources.
    trusted = recall.groupby("instrument")["trusted_pre_filter"].max() if not recall.empty else pd.Series(dtype=bool)
    snapshot["trusted_pre_filter"] = trusted.reindex(snapshot.index).fillna(False)
    result = build_factory(snapshot, recall)
    output = args.output or OUTPUT_DIR / f"candidate_factory_{datetime.now():%Y%m%d_%H%M%S}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_json_safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"candidate union={result['counts']['union']} lite={result['counts']['lite']} "
        f"medium={result['counts']['medium']} deep={result['counts']['deep']}"
    )
    print(f"result: {output}")
    return result


if __name__ == "__main__":
    main()
