from pathlib import Path

import pandas as pd
import pytest

from analyze_x02_execution_stability import (
    DAILY_NAME,
    analyze_stability,
    calendar_year_returns,
    compounded_return,
    rolling_compounded,
    summarize_rolling,
    validate_daily_lineage,
)
from x02_provenance import sha256_file


def test_compounded_return_matches_two_period_growth():
    assert compounded_return([0.10, -0.05]) == pytest.approx(0.045)


def test_rolling_compounded_uses_fixed_window_without_annualizing():
    s = pd.Series([0.01] * 5, index=pd.date_range("2024-01-02", periods=5, freq="D"))
    r = rolling_compounded(s, 3)
    assert len(r) == 3
    assert r.iloc[0] == pytest.approx((1.01 ** 3) - 1.0)


def test_summarize_rolling_reports_positive_fraction_and_quantiles():
    s = pd.Series([0.01] * 6, index=pd.date_range("2024-01-02", periods=6, freq="D"))
    row = summarize_rolling(s, 3)
    assert row["n_windows"] == 4
    assert row["positive_fraction"] == 1.0
    assert row["worst"] > 0
    assert row["best"] > 0


def test_calendar_year_returns_are_separate():
    s = pd.Series(
        [0.10, 0.10, -0.10, 0.00],
        index=pd.to_datetime(["2024-01-02", "2024-12-30", "2025-01-02", "2025-12-30"]),
    )
    years = calendar_year_returns(s)
    assert years["2024"] == pytest.approx(0.21)
    assert years["2025"] == pytest.approx(-0.10)


def test_analyze_stability_marks_partial_last_year_and_fixed_windows():
    idx = pd.bdate_range("2024-01-02", periods=300)
    s = pd.Series([0.001] * len(idx), index=idx)
    result = analyze_stability(s)
    assert result["n_daily_returns"] == 300
    assert set(result["rolling_windows"]) == {"126", "252"}
    assert result["rolling_windows"]["126"]["n_windows"] == 175
    assert result["positive_calendar_year_fraction"] == 1.0


def test_manifest_hash_binds_primary_daily_series(tmp_path: Path):
    daily = tmp_path / DAILY_NAME
    daily.write_text("date,net_return\n2024-01-02,0.01\n", encoding="utf-8")
    manifest = {
        "pass": True,
        "artifacts": {DAILY_NAME: {"sha256": sha256_file(daily)}},
    }
    assert validate_daily_lineage(manifest, daily)["pass"] is True
    daily.write_text("date,net_return\n2024-01-02,0.02\n", encoding="utf-8")
    result = validate_daily_lineage(manifest, daily)
    assert result["pass"] is False
    assert any("hash mismatch" in failure for failure in result["failures"])
