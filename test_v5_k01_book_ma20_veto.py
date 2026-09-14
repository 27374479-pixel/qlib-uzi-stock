import pandas as pd

import v5_k01_book_ma20_veto as k01


def _frame():
    dates = pd.bdate_range("2024-01-02", periods=25)
    closes_a = [10.0 + 0.1 * i for i in range(25)]
    closes_b = [20.0 - 0.1 * i for i in range(25)]
    return pd.DataFrame({
        "instrument": ["A"] * 25 + ["B"] * 25,
        "date": list(dates) * 2,
        "close": closes_a + closes_b,
    })


def test_literal_ma20_direction_sign_only():
    x = k01.add_ma20_direction(_frame())
    a = x.loc[x["instrument"].eq("A")].iloc[-1]
    b = x.loc[x["instrument"].eq("B")].iloc[-1]
    assert bool(a["ma20_valid"])
    assert bool(a["ma20_non_down"])
    assert not bool(a["ma20_down"])
    assert bool(b["ma20_down"])
    assert not bool(b["ma20_non_down"])


def test_no_signal_before_ma20_and_prior_ma20_exist():
    x = k01.add_ma20_direction(_frame())
    a = x.loc[x["instrument"].eq("A")].reset_index(drop=True)
    assert not bool(a.loc[19, "ma20_valid"])
    assert bool(a.loc[20, "ma20_valid"])


def _block(diff=0.002, lower=0.001, control_excess=-0.001, n=2000, days=400):
    return {
        "selected": {"n": n, "active_days": days},
        "control": {"n": n, "active_days": days, "mean_market_excess": control_excess},
        "paired": {
            "paired_days": days,
            "expected_signed_difference": diff,
            "bootstrap95_expected_signed_difference": [lower, 0.004],
        },
    }


def test_k01_gate_requires_both_segments_and_negative_downward_excess():
    result = k01.qualification(_block(), _block())
    assert result["status"] == "VALIDATED_AS_RISK_VETO"
    assert result["validated_as_risk_veto"] is True
    assert result["retrofit_prior_experiments"] is False


def test_nonpositive_paired_lower_bound_does_not_validate():
    result = k01.qualification(_block(lower=0.0), _block())
    assert result["status"] == "NOT_VALIDATED"


def test_positive_downward_market_excess_does_not_validate():
    result = k01.qualification(_block(control_excess=0.001), _block())
    assert result["status"] == "NOT_VALIDATED"


def test_k01_config_is_bound_to_k01_outputs_and_contract_has_no_search():
    config = k01.screen_config()
    assert config.output == "output/v5_k01_book_ma20_veto/report.json"
    assert config.observations_output == "output/v5_k01_book_ma20_veto/observations.parquet"
    assert k01.CONTRACT["parameter_search"] is False
