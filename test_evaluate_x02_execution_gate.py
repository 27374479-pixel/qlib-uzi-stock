from evaluate_x02_execution_gate import evaluate, render_markdown


def _inputs(cagr=0.12, bar_pass=True, lineage_pass=True):
    bar = {
        "validation": {"pass": bar_pass},
        "aggregate": {"inference": "CONSISTENT_WITH_END_LABELLED_5M_NOT_PROOF"},
    }
    comparison = {
        "lineage": {"pass": lineage_pass},
        "results": {
            "original_gate_CONSERVATIVE": {
                "later": {
                    "next_bar": {"cagr": cagr, "max_drawdown": -0.25},
                    "positive_metric_retention": {"cagr": 0.6},
                    "execution": {"fill_rate": 0.9, "cash_slots": 15},
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
