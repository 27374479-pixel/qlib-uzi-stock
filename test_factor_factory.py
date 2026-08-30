import numpy as np
import pandas as pd

from auto_factor_backtest import matured_train_dates
from factor_factory import (
    FactorExpression,
    FactorRegistry,
    BalancedGenerator,
    apply_oos_evidence,
    evaluate_candidates,
    rank_factor_matrix,
    select_diverse_factors,
)


def _panel() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = pd.date_range("2024-01-01", periods=6, freq="ME")
    index = pd.MultiIndex.from_product([dates, [f"s{i:03d}" for i in range(40)]], names=["datetime", "instrument"])
    signal = rng.normal(size=len(index))
    return pd.DataFrame(
        {
            "a": signal,
            "a_copy": signal,
            "b": rng.normal(size=len(index)),
            "target": signal * 0.2 + rng.normal(scale=0.05, size=len(index)),
        },
        index=index,
    )


def test_factor_dsl_is_finite_and_serialisable():
    frame = pd.DataFrame({"a": [-4.0, 0.0, 9.0], "b": [0.0, 2.0, -3.0]})
    expressions = [
        FactorExpression("signed_sqrt", "a"),
        FactorExpression("log_abs", "a"),
        FactorExpression("difference", "a", "b"),
        FactorExpression("ratio", "a", "b"),
    ]

    values = pd.concat([expression.evaluate(frame) for expression in expressions], axis=1)

    assert not np.isinf(values.to_numpy()).any()
    assert expressions[-1].name == "ratio(a,b)"
    assert expressions[-1].complexity == 3


def test_rank_factor_matrix_accepts_single_current_snapshot():
    frame = pd.DataFrame({"a": [3.0, 1.0, 2.0]}, index=["s1", "s2", "s3"])

    ranked = rank_factor_matrix(frame, [FactorExpression("base", "a")])

    assert ranked.loc["s2", "a"] < ranked.loc["s3", "a"] < ranked.loc["s1", "a"]


def test_selection_removes_correlated_duplicate():
    panel = _panel()
    expressions = [FactorExpression("base", name) for name in ("a", "a_copy", "b")]
    ranked = rank_factor_matrix(panel, expressions)
    metrics = evaluate_candidates(ranked, panel["target"], expressions)

    selected = select_diverse_factors(metrics, ranked, count=3, max_abs_correlation=0.80, min_abs_ic=0.0)

    assert "a" in selected or "a_copy" in selected
    assert not ({"a", "a_copy"} <= set(selected))


def test_matured_train_dates_excludes_two_latest_snapshots():
    dates = list(pd.date_range("2024-01-01", periods=10, freq="21D"))

    selected = matured_train_dates(dates, period=8, train_periods=4)

    assert selected == dates[2:6]
    assert dates[6] not in selected and dates[7] not in selected


def test_registry_promotes_then_retires_factor():
    metrics = pd.DataFrame(
        [{"name": "a", "mean_ic": 0.03, "ic_ir": 0.4, "orientation": 1, "score": 0.02}]
    )
    registry = FactorRegistry(promote_after=2, retire_after=2)
    registry.update(metrics, ["a"], pd.Timestamp("2024-01-01"))
    assert registry.records["a"]["status"] == "challenger"
    registry.update(metrics, ["a"], pd.Timestamp("2024-02-01"))
    assert registry.records["a"]["status"] == "champion"
    registry.record_oos("a", 0.04, pd.Timestamp("2024-02-01"))
    assert registry.records["a"]["mean_oos_ic"] == 0.04
    registry.update(metrics, [], pd.Timestamp("2024-03-01"))
    registry.update(metrics, [], pd.Timestamp("2024-04-01"))
    assert registry.records["a"]["status"] == "retired"


def test_oos_evidence_rewards_only_matured_history():
    metrics = pd.DataFrame(
        [
            {"name": "good", "score": 1.0},
            {"name": "bad", "score": 1.0},
            {"name": "new", "score": 1.0},
        ]
    )
    registry = FactorRegistry()
    registry.records = {name: {"name": name} for name in ("good", "bad")}
    for period in range(6):
        registry.record_oos("good", 0.05, pd.Timestamp("2024-01-01") + pd.Timedelta(days=period))
        registry.record_oos("bad", -0.05, pd.Timestamp("2024-01-01") + pd.Timedelta(days=period))

    adjusted = apply_oos_evidence(metrics, registry).set_index("name")

    assert adjusted.loc["good", "score"] > adjusted.loc["new", "score"]
    assert adjusted.loc["bad", "score"] < adjusted.loc["new", "score"]
    assert adjusted.loc["new", "oos_multiplier"] == 1.0


def test_balanced_generator_keeps_every_binary_operator():
    expressions = BalancedGenerator().generate(("ret_5", "vol_20", "amount_ratio", "book_to_price"), limit=24)
    operations = {expression.op for expression in expressions}

    assert {"difference", "sum", "product", "ratio"} <= operations


def test_selection_respects_factor_family_budget():
    panel = _panel().rename(columns={"a": "ret_5", "a_copy": "ret_20", "b": "vol_20"})
    expressions_list = [
        FactorExpression("base", "ret_5"),
        FactorExpression("base", "ret_20"),
        FactorExpression("base", "vol_20"),
    ]
    ranked = rank_factor_matrix(panel, expressions_list)
    metrics = pd.DataFrame(
        [
            {"name": "ret_5", "mean_ic": 0.10, "score": 3.0},
            {"name": "ret_20", "mean_ic": 0.09, "score": 2.0},
            {"name": "vol_20", "mean_ic": 0.08, "score": 1.0},
        ]
    )
    selected = select_diverse_factors(
        metrics,
        ranked,
        count=3,
        max_abs_correlation=1.0,
        min_abs_ic=0.0,
        expressions={expression.name: expression for expression in expressions_list},
        max_per_family=1,
    )

    assert len(set(selected) & {"ret_5", "ret_20"}) == 1
    assert "vol_20" in selected
