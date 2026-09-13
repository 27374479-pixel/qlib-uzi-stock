from evaluate_x02_execution_gate import evaluate, render_markdown


def _inputs(cagr=0.12, bar_pass=True, lineage_pass=True, inference="CONSISTENT_WITH_END_LABELLED_5M_NOT_PROOF"):
    bar = {
        "validation": {"pass": bar_pass},
        "aggregate": {"inference": inference},
    }
    comparison = {
        "lineage": {"pass": lineage_pass},
        "results": {
            "original_gate_CONSERVATIVE": {
                "later": {
                    "next_bar": {"cagr": cagr, "max_drawdown": -0.25},
                    "positive_metric_retention": {"cagr": 0.6},
                    "execution": {
                        "fill_rate": 0.9,
                        "cash_slots": 15,
                        "mean_entry_slippage_vs_1445": 0.004,
                        "unfilled_reasons": {"limit_buffer_fail": 10, "missing_next_record": 5},
                    },
                }
            }
        },
    }
    return bar, comparison


def test_positive_primary_result_allows_paper_trading_only():
    bar, comparison = _inputs(0.12)
    result = evaluate(bar, comparison)
    assert result["status"] == "PROVISIONALLY_ROBUST_FOR_PAPER_TRADING_ONLY"
    assert result["paper_trading_authorized"] is True
    assert result["live_trading_authorized"] is False
    assert result["post_result_retuning_authorized"] is False
    assert result["primary_mean_entry_slippage_vs_1445"] == 0.004


def test_nonpositive_primary_result_fails_execution_survival():
    bar, comparison = _inputs(0.0)
    result = evaluate(bar, comparison)
    assert result["status"] == "EXECUTION_NOT_ROBUST"
    assert result["paper_trading_authorized"] is False


def test_failed_data_audit_makes_gate_technically_invalid():
    bar, comparison = _inputs(0.12, bar_pass=False)
    result = evaluate(bar, comparison)
    assert result["status"] == "TECHNICALLY_INVALID"
    assert result["paper_trading_authorized"] is False


def test_ambiguous_bar_label_structure_makes_gate_invalid():
    bar, comparison = _inputs(0.12, inference="LABEL_SEMANTICS_AMBIGUOUS")
    result = evaluate(bar, comparison)
    assert result["status"] == "TECHNICALLY_INVALID"
    assert result["paper_trading_authorized"] is False
    assert any("label structure remains ambiguous" in reason for reason in result["reasons"])


def test_failed_lineage_makes_gate_invalid():
    bar, comparison = _inputs(0.12, lineage_pass=False)
    result = evaluate(bar, comparison)
    assert result["status"] == "TECHNICALLY_INVALID"


def test_missing_primary_result_is_invalid():
    bar, comparison = _inputs(0.12)
    comparison["results"] = {}
    result = evaluate(bar, comparison)
    assert result["status"] == "TECHNICALLY_INVALID"


def test_markdown_never_claims_live_authorization():
    bar, comparison = _inputs(0.12)
    text = render_markdown(evaluate(bar, comparison))
    assert "Live trading authorized: False" in text
    assert "PROVISIONALLY_ROBUST_FOR_PAPER_TRADING_ONLY" in text
    assert "Mean entry slippage vs 14:45: 0.40%" in text
