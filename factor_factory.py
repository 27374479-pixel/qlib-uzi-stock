"""Auditable automatic factor discovery primitives.

The module deliberately separates candidate generation from evaluation.  An LLM
or RD-Agent can later implement ``CandidateGenerator`` without gaining access to
the out-of-sample evaluator or portfolio returns.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

import numpy as np
import pandas as pd


BASE_FEATURES = (
    "ret_5",
    "ret_20",
    "ret_60",
    "mom_6_1",
    "mom_12_1",
    "vol_20",
    "vol_60",
    "downside_60",
    "range_20",
    "amount_ratio",
)


@dataclass(frozen=True)
class FactorExpression:
    """A small serialisable factor DSL with no arbitrary code execution."""

    op: str
    left: str
    right: str | None = None

    @property
    def name(self) -> str:
        if self.op == "base":
            return self.left
        if self.right is None:
            return f"{self.op}({self.left})"
        return f"{self.op}({self.left},{self.right})"

    @property
    def complexity(self) -> int:
        return 1 if self.op == "base" else (2 if self.right is None else 3)

    def evaluate(self, frame: pd.DataFrame) -> pd.Series:
        left = frame[self.left].astype(float)
        if self.op == "base":
            value = left
        elif self.op == "signed_sqrt":
            value = np.sign(left) * np.sqrt(np.abs(left))
        elif self.op == "log_abs":
            value = np.sign(left) * np.log1p(np.abs(left))
        else:
            if self.right is None:
                raise ValueError(f"Operation {self.op!r} requires a right operand")
            right = frame[self.right].astype(float)
            if self.op == "difference":
                value = left - right
            elif self.op == "sum":
                value = left + right
            elif self.op == "product":
                value = left * right
            elif self.op == "ratio":
                scale = float(np.nanmedian(np.abs(right.to_numpy())))
                floor = max(scale * 0.05, 1e-8)
                denominator = right.where(np.abs(right) >= floor)
                value = left / denominator
            else:
                raise ValueError(f"Unknown factor operation: {self.op!r}")
        return pd.Series(value, index=frame.index, name=self.name).replace([np.inf, -np.inf], np.nan)


class CandidateGenerator(Protocol):
    def generate(self, base_features: tuple[str, ...], limit: int) -> list[FactorExpression]: ...


class DeterministicGenerator:
    """A reproducible starter generator; RD-Agent can replace this component."""

    def generate(self, base_features: tuple[str, ...] = BASE_FEATURES, limit: int = 120) -> list[FactorExpression]:
        result = [FactorExpression("base", feature) for feature in base_features]
        result += [FactorExpression(op, feature) for op in ("signed_sqrt", "log_abs") for feature in base_features]
        for op in ("difference", "sum", "product", "ratio"):
            for i, left in enumerate(base_features):
                for right in base_features[i + 1 :]:
                    result.append(FactorExpression(op, left, right))
                    if len(result) >= limit:
                        return result
        return result[:limit]


class BalancedGenerator:
    """Sample every operator and operand region instead of prefix truncation."""

    OPERATIONS = ("difference", "sum", "product", "ratio")

    def generate(self, base_features: tuple[str, ...] = BASE_FEATURES, limit: int = 120) -> list[FactorExpression]:
        result = [FactorExpression("base", feature) for feature in base_features]
        result += [FactorExpression(op, feature) for op in ("signed_sqrt", "log_abs") for feature in base_features]
        if len(result) >= limit:
            return result[:limit]
        pairs = [(left, right) for i, left in enumerate(base_features) for right in base_features[i + 1 :]]
        remaining = limit - len(result)
        quotas = [remaining // len(self.OPERATIONS)] * len(self.OPERATIONS)
        for index in range(remaining % len(self.OPERATIONS)):
            quotas[index] += 1
        # A coprime stride spreads each operator across the full operand list.
        stride = max(1, len(pairs) - 1)
        for op_number, (op, quota) in enumerate(zip(self.OPERATIONS, quotas)):
            chosen = []
            cursor = op_number * 7
            while len(chosen) < min(quota, len(pairs)):
                pair = pairs[cursor % len(pairs)]
                if pair not in chosen:
                    chosen.append(pair)
                cursor += stride
            result.extend(FactorExpression(op, left, right) for left, right in chosen)
        return result[:limit]


def factor_families(expression: FactorExpression) -> set[str]:
    def family(feature: str) -> str:
        if feature.startswith(("ret_", "mom_")):
            return "trend"
        if feature.startswith(("vol_", "downside_", "range_")):
            return "risk"
        if feature.startswith(("amount", "turnover")):
            return "liquidity"
        if feature in {"earnings_yield", "book_to_price", "sales_to_price", "cashflow_yield"}:
            return "value"
        if feature == "log_float_market_cap":
            return "size"
        return "other"

    return {family(expression.left)} | ({family(expression.right)} if expression.right else set())


@dataclass(frozen=True)
class FactorMetric:
    name: str
    mean_ic: float
    ic_ir: float
    oriented_positive_rate: float
    coverage: float
    observations: int
    orientation: int
    complexity: int
    score: float


def _date_level(frame: pd.DataFrame) -> str | int:
    if not isinstance(frame.index, pd.MultiIndex):
        raise ValueError("Factor evaluation requires a MultiIndex panel")
    return "datetime" if "datetime" in frame.index.names else 0


def rank_factor_matrix(frame: pd.DataFrame, expressions: list[FactorExpression]) -> pd.DataFrame:
    """Evaluate expressions and cross-sectionally rank them by date."""

    values = pd.concat([expression.evaluate(frame) for expression in expressions], axis=1)
    if isinstance(frame.index, pd.MultiIndex):
        return values.groupby(level=_date_level(frame)).rank(pct=True)
    # A live/current snapshot is already a single cross-section indexed by instrument.
    return values.rank(pct=True)


def evaluate_candidates(
    ranked: pd.DataFrame,
    target: pd.Series,
    expressions: list[FactorExpression],
    min_cross_section: int = 20,
) -> pd.DataFrame:
    """Evaluate candidates using only the supplied (training) panel."""

    target_rank = target.groupby(level=_date_level(target.to_frame())).rank(pct=True)
    rows: list[dict] = []
    for expression in expressions:
        pair = pd.concat([ranked[expression.name], target_rank.rename("target")], axis=1).dropna()
        coverage = float(len(pair) / max(len(target), 1))
        ics = []
        for _, group in pair.groupby(level=_date_level(pair)):
            if len(group) >= min_cross_section:
                ics.append(group.iloc[:, 0].corr(group.iloc[:, 1], method="pearson"))
        clean = np.asarray([value for value in ics if np.isfinite(value)], dtype=float)
        if len(clean) == 0:
            mean_ic = ic_ir = positive_rate = score = np.nan
            orientation = 1
        else:
            mean_ic = float(clean.mean())
            std = float(clean.std(ddof=1)) if len(clean) > 1 else np.nan
            ic_ir = mean_ic / std if np.isfinite(std) and std > 0 else 0.0
            orientation = 1 if mean_ic >= 0 else -1
            oriented = clean * orientation
            positive_rate = float((oriented > 0).mean())
            stability = min(abs(ic_ir), 2.0) / 2.0
            complexity_penalty = 1.0 + 0.15 * (expression.complexity - 1)
            score = abs(mean_ic) * (0.5 + 0.25 * positive_rate + 0.25 * stability) * coverage / complexity_penalty
        rows.append(
            asdict(
                FactorMetric(
                    name=expression.name,
                    mean_ic=mean_ic,
                    ic_ir=ic_ir,
                    oriented_positive_rate=positive_rate,
                    coverage=coverage,
                    observations=len(clean),
                    orientation=orientation,
                    complexity=expression.complexity,
                    score=score,
                )
            )
        )
    return pd.DataFrame(rows).sort_values("score", ascending=False, na_position="last").reset_index(drop=True)


def select_diverse_factors(
    metrics: pd.DataFrame,
    ranked: pd.DataFrame,
    count: int = 12,
    max_abs_correlation: float = 0.70,
    min_abs_ic: float = 0.005,
    expressions: dict[str, FactorExpression] | None = None,
    max_per_family: int | None = None,
) -> list[str]:
    """Greedily keep high-scoring factors while removing pooled redundancy."""

    eligible = metrics.loc[metrics["mean_ic"].abs() >= min_abs_ic, "name"].tolist()
    selected: list[str] = []
    family_counts: dict[str, int] = {}
    for name in eligible:
        families = factor_families(expressions[name]) if expressions is not None and name in expressions else set()
        if max_per_family is not None and any(family_counts.get(family, 0) >= max_per_family for family in families):
            continue
        if not selected:
            selected.append(name)
        else:
            correlations = ranked[selected].corrwith(ranked[name]).abs()
            if correlations.fillna(1.0).max() <= max_abs_correlation:
                selected.append(name)
        if selected and selected[-1] == name:
            for family in families:
                family_counts[family] = family_counts.get(family, 0) + 1
        if len(selected) >= count:
            break
    return selected


def apply_oos_evidence(
    metrics: pd.DataFrame,
    registry: "FactorRegistry",
    min_observations: int = 4,
    shrinkage_observations: float = 8.0,
) -> pd.DataFrame:
    """Adjust training scores using only already-matured OOS RankIC evidence.

    New factors remain eligible with multiplier 1.  Evidence is deliberately
    shrunk toward zero and its influence is bounded, preventing a short lucky
    streak from permanently monopolising the factor zoo.
    """

    adjusted = metrics.copy()
    adjusted["training_score"] = adjusted["score"]
    observations = []
    means = []
    multipliers = []
    for name in adjusted["name"]:
        record = registry.records.get(name, {})
        history = record.get("oos_history", [])
        values = np.asarray([item["rank_ic"] for item in history], dtype=float)
        observations.append(len(values))
        mean = float(values.mean()) if len(values) else np.nan
        means.append(mean)
        if len(values) < min_observations:
            multipliers.append(1.0)
            continue
        shrunk = mean * len(values) / (len(values) + shrinkage_observations)
        multiplier = float(np.clip(np.exp(8.0 * shrunk), 0.50, 1.50))
        recent = values[-6:]
        if len(recent) >= min_observations and float(recent.mean()) < -0.01:
            multiplier = min(multiplier, 0.65)
        multipliers.append(multiplier)
    adjusted["oos_observations"] = observations
    adjusted["mean_oos_ic"] = means
    adjusted["oos_multiplier"] = multipliers
    adjusted["score"] = adjusted["training_score"] * adjusted["oos_multiplier"]
    return adjusted.sort_values("score", ascending=False, na_position="last").reset_index(drop=True)


class FactorRegistry:
    """Small champion/challenger registry driven by chronological selections."""

    def __init__(self, promote_after: int = 2, retire_after: int = 12):
        self.promote_after = promote_after
        self.retire_after = retire_after
        self.period = -1
        self.records: dict[str, dict] = {}

    def update(self, metrics: pd.DataFrame, selected: list[str], signal_date: pd.Timestamp) -> None:
        self.period += 1
        metric_map = metrics.set_index("name").to_dict("index")
        for name, metric in metric_map.items():
            record = self.records.setdefault(
                name,
                {"name": name, "status": "candidate", "selection_count": 0, "consecutive": 0, "last_selected_period": None},
            )
            record["latest_metric"] = {key: _native(value) for key, value in metric.items()}
            record["last_evaluated"] = str(pd.Timestamp(signal_date).date())
            if name in selected:
                record["consecutive"] = record["consecutive"] + 1 if record["last_selected_period"] == self.period - 1 else 1
                record["selection_count"] += 1
                record["last_selected_period"] = self.period
                record["status"] = "champion" if record["consecutive"] >= self.promote_after else "challenger"
            elif record["last_selected_period"] is not None and self.period - record["last_selected_period"] >= self.retire_after:
                record["consecutive"] = 0
                record["status"] = "retired"
            elif record["status"] != "retired":
                record["consecutive"] = 0
                record["status"] = "candidate"

    def snapshot(self) -> list[dict]:
        return sorted(self.records.values(), key=lambda item: (item["status"], -item["selection_count"], item["name"]))

    def record_oos(self, name: str, rank_ic: float, signal_date: pd.Timestamp) -> None:
        """Attach a matured OOS observation without using it retroactively."""

        if name not in self.records or not np.isfinite(rank_ic):
            return
        history = self.records[name].setdefault("oos_history", [])
        history.append({"signal_date": str(pd.Timestamp(signal_date).date()), "rank_ic": float(rank_ic)})
        values = np.asarray([item["rank_ic"] for item in history], dtype=float)
        self.records[name]["oos_observations"] = len(values)
        self.records[name]["mean_oos_ic"] = float(values.mean())


def _native(value):
    if isinstance(value, np.generic):
        return value.item()
    return value
