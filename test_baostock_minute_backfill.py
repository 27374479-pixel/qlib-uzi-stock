from __future__ import annotations

import pandas as pd
import pytest

import baostock_minute_backfill as collector
from baostock_minute_backfill import _merge_cached, _normalise_rows


def test_baostock_rows_are_unadjusted_point_in_time_bars() -> None:
    rows = [[
        "2026-06-01",
        "20260601093500000",
        "9.3200",
        "9.3400",
        "9.2000",
        "9.2300",
        "10733400",
        "99268494.0000",
    ]]
    result = _normalise_rows(
        rows,
        "SH600000",
        "2026-08-24T17:00:00",
        pd.Timestamp("2026-06-01"),
        pd.Timestamp("2026-08-24"),
    )
    assert len(result) == 1
    assert result.loc[0, "datetime"] == pd.Timestamp("2026-06-01 09:35")
    assert result.loc[0, "source"] == "baostock_5min"
    assert result.loc[0, "knowledge_time"] == result.loc[0, "datetime"]
    assert result.loc[0, "close"] == 9.23


def test_source_merge_prefers_eastmoney_then_baostock_then_sina() -> None:
    base = pd.DataFrame(
        {
            "instrument": ["SH600000", "SH600001"],
            "datetime": [pd.Timestamp("2026-06-01 09:35"), pd.Timestamp("2026-06-01 09:35")],
            "close": [1.0, 3.0],
            "source": ["sina_5min_via_akshare", "eastmoney_push2his_5min"],
        }
    )
    fresh = pd.DataFrame(
        {
            "instrument": ["SH600000", "SH600001"],
            "datetime": [pd.Timestamp("2026-06-01 09:35"), pd.Timestamp("2026-06-01 09:35")],
            "close": [2.0, 4.0],
            "source": ["baostock_5min", "baostock_5min"],
        }
    )
    result = _merge_cached(base, fresh).set_index("instrument")
    assert result.loc["SH600000", "close"] == 2.0
    assert result.loc["SH600000", "source"] == "baostock_5min"
    assert result.loc["SH600001", "close"] == 3.0
    assert result.loc["SH600001", "source"] == "eastmoney_push2his_5min"


def test_repeated_provider_page_is_rejected(monkeypatch) -> None:
    row = [
        "2026-06-01", "20260601093500000", "9.32", "9.34",
        "9.20", "9.23", "10733400", "99268494",
    ]

    class RepeatingResult:
        error_code = "0"
        error_msg = ""
        cur_page_num = "1"
        cur_row_num = 0
        data = [row]

        def next(self):
            self.cur_page_num = str(int(self.cur_page_num) + 1)
            self.cur_row_num = 0
            self.data = [row]
            return True

    monkeypatch.setattr(
        collector.bs,
        "query_history_k_data_plus",
        lambda *args, **kwargs: RepeatingResult(),
    )
    with pytest.raises(RuntimeError, match="repeated pagination content"):
        collector._query_symbol(
            "SH600000",
            pd.Timestamp("2026-06-01"),
            pd.Timestamp("2026-06-01"),
            "2026-08-25T10:00:00",
        )
