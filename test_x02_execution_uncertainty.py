import json
from pathlib import Path

import numpy as np

from analyze_x02_execution_uncertainty_v2 import (
    annualized_cagr,
    max_drawdown,
    moving_block_bootstrap,
    validate_daily_lineage,
)
from x02_provenance import sha256_file


def test_positive_constant_returns_have_positive_cagr_and_zero_drawdown():
    values = np.array([0.001] * 40)
    assert annualized_cagr(values) > 0
    assert max_drawdown(values) == 0.0


def test_moving_block_bootstrap_is_deterministic_for_fixed_seed():
    values = np.array([0.01, -0.005, 0.002, 0.0] * 10)
    a = moving_block_bootstrap(values, block_length=4, samples=100, seed=7)
    b = moving_block_bootstrap(values, block_length=4, samples=100, seed=7)
    assert a == b
    assert a["cagr_p05"] <= a["cagr_p50"] <= a["cagr_p95"]
    assert 0.0 <= a["cagr_probability_positive"] <= 1.0


def test_daily_lineage_accepts_matching_hash(tmp_path: Path):
    daily = tmp_path / "daily.csv"
    daily.write_text("date,net_return\n2024-01-02,0.01\n", encoding="utf-8")
    manifest = {
        "pass": True,
        "artifacts": {
            "original_gate_CONSERVATIVE_next_bar_daily.csv": {"sha256": sha256_file(daily)}
        },
    }
    result = validate_daily_lineage(manifest, daily)
    assert result["pass"] is True


def test_daily_lineage_rejects_hash_mismatch(tmp_path: Path):
    daily = tmp_path / "daily.csv"
    daily.write_text("date,net_return\n2024-01-02,0.01\n", encoding="utf-8")
    manifest = {
        "pass": True,
        "artifacts": {
            "original_gate_CONSERVATIVE_next_bar_daily.csv": {"sha256": "wrong"}
        },
    }
    result = validate_daily_lineage(manifest, daily)
    assert result["pass"] is False
