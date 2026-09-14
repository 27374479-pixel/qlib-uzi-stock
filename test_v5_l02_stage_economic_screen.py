import pandas as pd

import v5_l01_leader_stage_transition_audit as l01
import v5_l02_stage_economic_screen as l02


def _stage_frame():
    return pd.DataFrame(
        {
            "instrument": ["A"] * 6 + ["B"] * 4,
            "date": list(pd.bdate_range("2024-01-02", periods=6))
            + list(pd.bdate_range("2024-01-02", periods=4)),
            "seal_up": [True, True, True, False, True, False, True, True, True, False],
            "board_height": [1, 2, 3, 0, 1, 0, 1, 2, 3, 0],
        }
    )


def test_l02_uses_exact_frozen_l01_confirmation_and_disagreement_labels():
    labelled = l01.annotate_stages(_stage_frame())
    selected, control = l02.cohorts(labelled)
    assert set(selected["stage_proxy"]) == {"confirmation"}
    assert set(control["stage_proxy"]) == {"disagreement"}
    assert len(selected) == 2
    assert len(control) == 2


def test_future_row_cannot_change_an_existing_l02_stage_label():
    base = _stage_frame()
    first = l01.annotate_stages(base)
    key = ("B", pd.Timestamp("2024-01-03"))
    before = first.loc[(first["instrument"] == key[0]) & (first["date"] == key[1]), "stage_proxy"].iloc[0]

    extra = pd.DataFrame(
        {
            "instrument": ["B"],
            "date": [pd.Timestamp("2024-01-08")],
            "seal_up": [False],
            "board_height": [0],
        }
    )
    second = l01.annotate_stages(pd.concat([base, extra], ignore_index=True))
    after = second.loc[(second["instrument"] == key[0]) & (second["date"] == key[1]), "stage_proxy"].iloc[0]
    assert before == "confirmation"
    assert after == "confirmation"


def _primary(
    selected_n=60,
    selected_days=35,
    control_n=40,
    control_days=25,
    paired_days=25,
    mean_return=0.01,
    mean_excess=0.004,
    diff=0.003,
    lower=0.001,
):
    return {
        "selected": {
            "n": selected_n,
            "active_days": selected_days,
            "mean_return": mean_return,
            "mean_market_excess": mean_excess,
        },
        "control": {"n": control_n, "active_days": control_days},
        "paired": {
            "paired_days": paired_days,
            "expected_signed_difference": diff,
            "bootstrap95_expected_signed_difference": [lower, 0.01],
        },
    }


def test_qualification_requires_both_frozen_partitions_to_pass():
    result = l02.qualification_from_primary(_primary(), _primary())
    assert result["status"] == "QUALIFIED_FOR_EXECUTION_VALIDATION_ONLY"
    assert result["qualified_for_execution_validation"] is True
    assert result["paper_trading_authorized"] is False
    assert result["live_trading_authorized"] is False


def test_sample_gate_failure_is_insufficient_not_rejected_or_passed():
    result = l02.qualification_from_primary(_primary(paired_days=19), _primary())
    assert result["status"] == "INSUFFICIENT"
    assert result["qualified_for_execution_validation"] is False
    assert any("paired" in reason for reason in result["reasons"])


def test_control_coverage_is_part_of_the_frozen_sample_gate():
    result = l02.qualification_from_primary(_primary(control_n=29), _primary())
    assert result["status"] == "INSUFFICIENT"
    assert any("disagreement observations" in reason for reason in result["reasons"])


def test_sufficient_sample_with_nonpositive_primary_difference_is_rejected():
    result = l02.qualification_from_primary(_primary(diff=0.0), _primary())
    assert result["status"] == "REJECTED"
    assert result["qualified_for_execution_validation"] is False


def test_sufficient_sample_with_nonpositive_bootstrap_lower_bound_is_rejected():
    result = l02.qualification_from_primary(_primary(lower=0.0), _primary())
    assert result["status"] == "REJECTED"
    assert any("bootstrap" in reason for reason in result["reasons"])


def test_contract_freezes_stage_pair_horizon_cost_and_no_live_authority():
    assert l02.CONTRACT["selected_stage"] == "confirmation"
    assert l02.CONTRACT["control_stage"] == "disagreement"
    assert l02.PRIMARY_HORIZON == 2
    assert l02.ROUND_TRIP_COST == 0.0036
    assert l02.CONTRACT["parameter_search"] is False
    assert l02.CONTRACT["stage_pair_search"] is False
    assert l02.CONTRACT["portfolio_combination_authorized"] is False
    assert l02.CONTRACT["paper_trading_authorized"] is False
    assert l02.CONTRACT["live_trading_authorized"] is False
