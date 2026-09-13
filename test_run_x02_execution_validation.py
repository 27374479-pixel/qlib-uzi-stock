from pathlib import Path

from run_x02_execution_validation import EXPECTED_OUTPUTS, artifact_fingerprints, build_plan


def test_default_plan_runs_all_frozen_stages_in_order():
    assert build_plan(False) == [
        ("minute_bar_structure", "audit_x02_minute_bar_structure.py"),
        ("legacy_reproduction", "reproduce_x02_local.py"),
        ("next_bar_execution", "audit_x02_next_bar_execution.py"),
        ("execution_artifact_binding", "bind_x02_execution_artifacts.py"),
        ("comparison", "compare_x02_next_bar_execution.py"),
        ("execution_uncertainty", "analyze_x02_execution_uncertainty.py"),
        ("execution_stability", "analyze_x02_execution_stability.py"),
        ("execution_gate", "evaluate_x02_execution_gate.py"),
        ("paper_trial_readiness", "prepare_x02_paper_trial.py"),
    ]


def test_reuse_plan_skips_only_legacy_reproduction():
    names = [name for name, _ in build_plan(True)]
    assert names == [
        "minute_bar_structure",
        "next_bar_execution",
        "execution_artifact_binding",
        "comparison",
        "execution_uncertainty",
        "execution_stability",
        "execution_gate",
        "paper_trial_readiness",
    ]


def test_artifact_fingerprints_are_explicit_about_missing_outputs(tmp_path: Path):
    present = tmp_path / EXPECTED_OUTPUTS[0]
    present.write_text("ok", encoding="utf-8")
    result = artifact_fingerprints(tmp_path)
    assert result[EXPECTED_OUTPUTS[0]]["exists"] is True
    assert result[EXPECTED_OUTPUTS[0]]["sha256"]
    assert result[EXPECTED_OUTPUTS[1]]["exists"] is False
    assert result[EXPECTED_OUTPUTS[1]]["sha256"] is None


def test_gate_selection_uncertainty_stability_and_paper_outputs_are_expected_artifacts():
    assert "execution_gate.json" in EXPECTED_OUTPUTS
    assert "execution_gate.md" in EXPECTED_OUTPUTS
    assert "original_gate_selected.parquet" in EXPECTED_OUTPUTS
    assert "no_market_gate_selected.parquet" in EXPECTED_OUTPUTS
    assert "execution_artifact_manifest.json" in EXPECTED_OUTPUTS
    assert "execution_uncertainty.json" in EXPECTED_OUTPUTS
    assert "execution_uncertainty.md" in EXPECTED_OUTPUTS
    assert "execution_stability.json" in EXPECTED_OUTPUTS
    assert "execution_stability.md" in EXPECTED_OUTPUTS
    assert "paper_trial_contract.json" in EXPECTED_OUTPUTS
    assert "paper_trial_readiness.json" in EXPECTED_OUTPUTS
