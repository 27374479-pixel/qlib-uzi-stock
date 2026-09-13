import pytest

from compare_x02_next_bar_execution import build_comparison, render_markdown


def _reports():
    legacy = {
        "contract": {"entry": "14:45 close"},
        "engine_sha256": "engine-hash",
        "features_sha256": "features-hash",
        "results": {
            "original_gate_BASE": {
                "all": {
                    "total_return": 0.5, "cagr": 0.10, "max_drawdown": -0.30,
                    "sharpe": 0.8, "active_days": 100,
                },
                "later": {
                    "total_return": 0.4, "cagr": 0.20, "max_drawdown": -0.20,
                    "sharpe": 1.0, "active_days": 50,
                },
            }
        },
    }
    stress = {
        "fill_proxy": "open of persisted 5m record labelled 14:50",
        "bar_label_contract": "label semantics audited separately",
        "inputs": {
            "engine_sha256": "engine-hash",
            "features_sha256": "features-hash",
            "report_sha256": "report-hash",
        },
        "results": {
            "original_gate_BASE": {
                "all": {
                    "total_return": 0.3, "cagr": 0.06, "max_drawdown": -0.35,
                    "sharpe": 0.5, "active_days": 90,
                    "selection_rows": 300, "filled_rows": 270, "fill_rate": 0.9,
                    "cash_slots": 30, "active_selection_days": 100,
                    "days_with_any_unfilled_slot": 20,
                },
                "later": {
                    "total_return": 0.25, "cagr": 0.12, "max_drawdown": -0.24,
                    "sharpe": 0.7, "active_days": 45,
                    "selection_rows": 150, "filled_rows": 135, "fill_rate": 0.9,
                    "cash_slots": 15, "active_selection_days": 50,
                    "days_with_any_unfilled_slot": 10,
                },
            }
        },
    }
    return legacy, stress


def test_build_comparison_reports_execution_deltas_and_retention():
    legacy, stress = _reports()
    result = build_comparison(legacy, stress)
    row = result["results"]["original_gate_BASE"]["all"]
    assert result["descriptive_only"] is True
    assert result["parameter_search"] is False
    assert result["lineage"]["pass"] is True
    assert row["delta"]["cagr"] == pytest.approx(-0.04)
    assert row["delta"]["max_drawdown"] == pytest.approx(-0.05)
    assert row["positive_metric_retention"]["cagr"] == pytest.approx(0.60)
    assert row["execution"]["fill_rate"] == pytest.approx(0.9)
    assert row["execution"]["cash_slots"] == 30


def test_markdown_contains_periods_fill_rate_and_retention():
    legacy, stress = _reports()
    text = render_markdown(build_comparison(legacy, stress))
    assert "original_gate_BASE" in text
    assert "later" in text
    assert "90.00%" in text
    assert "0.60x" in text
    assert "Descriptive execution-sensitivity report only" in text


def test_report_hash_mismatch_is_rejected_when_supplied():
    legacy, stress = _reports()
    with pytest.raises(ValueError, match="report hash"):
        build_comparison(legacy, stress, legacy_sha256="different-report-hash")


def test_no_common_result_keys_is_rejected():
    legacy, stress = _reports()
    legacy["results"] = {"a": {}}
    stress["results"] = {"b": {}}
    with pytest.raises(ValueError, match="no common result keys"):
        build_comparison(legacy, stress)
