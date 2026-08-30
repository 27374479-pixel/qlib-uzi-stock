from pathlib import Path

import pandas as pd

from auxiliary_data_loader import load_auxiliary_panel, load_industry_panel


def test_loader_uses_exact_dates_without_forward_fill(tmp_path: Path):
    source = pd.DataFrame(
        {
            "instrument": ["SH600000"],
            "date": [pd.Timestamp("2024-01-02")],
            "turnover_rate_pct": [1.2],
            "trade_status": [1],
            "is_st": [0],
            "pe_ttm": [6.0],
            "pb_mrq": [0.8],
            "ps_ttm": [2.0],
            "pcf_ncf_ttm": [5.0],
            "float_shares_est": [100.0],
            "float_market_cap_est": [1000.0],
        }
    )
    source.to_parquet(tmp_path / "SH600000.parquet", index=False)
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2024-01-02"), "SH600000"), (pd.Timestamp("2024-01-03"), "SH600000")],
        names=["datetime", "instrument"],
    )

    result = load_auxiliary_panel(index, tmp_path)

    assert result.iloc[0]["pe_ttm"] == 6.0
    assert pd.isna(result.iloc[1]["pe_ttm"])


def test_industry_loader_requires_exact_snapshot_date(tmp_path: Path):
    source = pd.DataFrame(
        {
            "snapshot_date": [pd.Timestamp("2024-01-02")],
            "instrument": ["SH600000"],
            "industry_code": ["J66"],
            "industry": ["J66货币金融服务"],
            "classification_standard": ["证监会行业分类"],
            "provider_update_date": [pd.Timestamp("2024-01-01")],
        }
    )
    source.to_parquet(tmp_path / "20240102.parquet", index=False)
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2024-01-02"), "SH600000"), (pd.Timestamp("2024-01-03"), "SH600000")],
        names=["datetime", "instrument"],
    )

    result = load_industry_panel(index, tmp_path)

    assert result.iloc[0]["industry_code"] == "J66"
    assert pd.isna(result.iloc[1]["industry_code"])
