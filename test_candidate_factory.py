import pandas as pd

from candidate_factory import FactoryConfig, build_factory, normalize_instrument


def _recall(*instruments: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument": [normalize_instrument(item) for item in instruments],
            "source": "qlib",
            "source_score": [1.0 - number * 0.1 for number in range(len(instruments))],
            "source_rank": list(range(1, len(instruments) + 1)),
        }
    )


def test_missing_financial_fields_deactivate_evidence_pools_without_fake_scores():
    snapshot = pd.DataFrame(
        {
            "trusted_pre_filter": [True, True],
            "ret20": [0.10, 0.08],
            "dist_ma20": [0.04, 0.03],
        },
        index=["SH600000", "SZ000001"],
    )

    result = build_factory(snapshot, _recall("SH600000", "SZ000001"))

    assert result["counts"]["lite"] == 2
    assert result["counts"]["medium"] == 0
    assert result["counts"]["deep"] == 0
    assert all(not item["active"] for item in result["pool_diagnostics"].values())


def test_earnings_pool_activates_and_routes_high_confidence_candidate():
    rows = []
    index = []
    for number in range(5):
        index.append(f"SH60000{number}")
        rows.append(
            {
                "close": 10.0,
                "amount_20": 100_000_000,
                "trade_status": 1,
                "is_st": 0,
                "pe_ttm": 20.0 + number,
                "pb_mrq": 2.0,
                "revenue_growth_yoy": 0.20 + number * 0.01,
                "profit_growth_yoy": 0.35 + number * 0.05,
                "cashflow_to_profit": 1.0,
                "nonrecurring_profit_share": 0.10,
                "debt_ratio": 0.35,
                "gross_margin_yoy_delta": 0.01,
            }
        )
    snapshot = pd.DataFrame(rows, index=index)

    result = build_factory(
        snapshot,
        _recall(*index),
        FactoryConfig(pool_quota=5, min_pool_coverage=0.8),
    )

    assert result["pool_diagnostics"]["earnings_inflection"]["active"]
    assert result["pool_diagnostics"]["earnings_inflection"]["selected_count"] == 5
    assert result["counts"]["medium"] == 5
    assert all(item["evidence_pool_count"] == 1 for item in result["candidates"])


def test_financial_red_flag_is_vetoed_before_uzi_queue():
    snapshot = pd.DataFrame(
        {
            "close": [10.0],
            "amount_20": [100_000_000],
            "trade_status": [1],
            "is_st": [0],
            "cashflow_to_profit": [0.2],
            "nonrecurring_profit_share": [0.6],
        },
        index=["SH600000"],
    )

    result = build_factory(snapshot, _recall("SH600000"))

    assert result["counts"]["vetoed"] == 1
    assert result["uzi_queues"]["lite"] == []
    reasons = result["candidates"][0]["veto_reasons"]
    assert "经营现金流/净利润低于0.5" in reasons
    assert "非经常损益占比超过30%" in reasons


def test_multiple_recall_sources_promote_candidate_to_medium_review():
    snapshot = pd.DataFrame(
        {"trusted_pre_filter": [True, True]},
        index=["SH600000", "SZ000001"],
    )
    recall = pd.concat(
        [
            _recall("SH600000", "SZ000001"),
            _recall("SH600000").assign(source="sequoia"),
        ],
        ignore_index=True,
    )

    result = build_factory(snapshot, recall)

    assert result["uzi_queues"]["medium"] == ["600000.SH"]
