import numpy as np

from point_in_time_data import normalize_baostock_daily, qlib_to_baostock, validate_frame


FIELDS = [
    "date", "code", "open", "high", "low", "close", "preclose", "volume", "amount",
    "adjustflag", "turn", "tradestatus", "pctChg", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM", "isST",
]


def test_symbol_conversion():
    assert qlib_to_baostock("SH600000") == "sh.600000"
    assert qlib_to_baostock("SZ000001") == "sz.000001"


def test_normalize_derives_point_in_time_float_market_cap():
    rows = [[
        "2024-01-02", "sh.600000", "10", "11", "9", "10", "9.8", "1000000", "10000000",
        "3", "2", "1", "2.04", "6", "0.8", "2", "5", "0",
    ]]

    frame = normalize_baostock_daily(rows, FIELDS, "SH600000")

    assert np.isclose(frame.iloc[0]["float_shares_est"], 50_000_000)
    assert np.isclose(frame.iloc[0]["float_market_cap_est"], 500_000_000)
    assert frame.iloc[0]["knowledge_date"] == frame.iloc[0]["date"]
    assert validate_frame(frame)["valid"]
