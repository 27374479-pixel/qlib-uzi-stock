from prepare_x02_paper_trial import (
    EXPECTED_LEGACY_CONTRACT,
    PAPER_TRIAL_CONTRACT,
    build_readiness,
    canonical_sha256,
)


def _report():
    return {"contract": dict(EXPECTED_LEGACY_CONTRACT)}


def _gate(authorized=True):
    return {
        "status": (
            "PROVISIONALLY_ROBUST_FOR_PAPER_TRADING_ONLY"
            if authorized
            else "EXECUTION_NOT_ROBUST"
        ),
        "paper_trading_authorized": authorized,
        "live_trading_authorized": False,
    }


def _uncertainty(valid=True):
    return {
        "lineage": {"pass": valid},
        "cagr_reconciliation": {"pass": valid},
    }


def _stability(valid=True):
    return {"lineage": {"pass": valid}}


def _manifest(valid=True):
    return {"pass": valid}


def test_ready_only_when_gate_and_all_lineage_checks_pass():
    result = build_readiness(_report(), _gate(), _uncertainty(), _stability(), _manifest())
    assert result["status"] == "READY_FOR_FORWARD_PAPER_TRIAL"
    assert result["ready"] is True
    assert result["paper_trading_authorized"] is True
    assert result["live_trading_authorized"] is False
    assert result["post_start_retuning_authorized"] is False


def test_failed_execution_gate_blocks_forward_trial():
    result = build_readiness(_report(), _gate(False), _uncertainty(), _stability(), _manifest())
    assert result["ready"] is False
    assert result["status"] == "NOT_AUTHORIZED_FOR_FORWARD_PAPER_TRIAL"
    assert any("execution gate" in reason for reason in result["reasons"])


def test_lineage_failure_blocks_forward_trial():
    result = build_readiness(_report(), _gate(), _uncertainty(False), _stability(), _manifest())
    assert result["ready"] is False
    assert any("uncertainty lineage" in reason for reason in result["reasons"])


def test_contract_mismatch_blocks_forward_trial():
    report = _report()
    report["contract"]["top_n"] = 4
    result = build_readiness(report, _gate(), _uncertainty(), _stability(), _manifest())
    assert result["ready"] is False
    assert any("top_n" in reason for reason in result["reasons"])


def test_paper_trial_contract_is_frozen_and_never_authorizes_live_trading():
    assert PAPER_TRIAL_CONTRACT["strategy"]["top_n"] == 3
    assert PAPER_TRIAL_CONTRACT["decision_and_execution"]["limit_buffer"] == 0.005
    assert PAPER_TRIAL_CONTRACT["forward_observation"]["minimum_trading_sessions"] == 126
    assert PAPER_TRIAL_CONTRACT["forward_observation"]["descriptive_checkpoints_trading_sessions"] == [21, 63, 126]
    assert PAPER_TRIAL_CONTRACT["live_trading_authorized"] is False
    assert len(canonical_sha256(PAPER_TRIAL_CONTRACT)) == 64
