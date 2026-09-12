import pandas as pd
import pytest

import audit_x02_next_bar_execution as audit
import v4_3_long_only_portfolio as engine


def _selected():
    return pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02"] * 3),
            "instrument": ["A", "B", "C"],
            "upper_limit": [12.0, 12.0, 12.0],
            "exit_1000": [11.0, 11.0, 11.0],
        }
    )


def test_unfilled_next_bar_slot_stays_cash_instead_of_reweighting():
    selected = _selected()
    next_bar = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02"] * 2),
            "instrument": ["A", "B"],
            "next_entry_open": [10.0, 10.0],
            "next_entry_volume": [100.0, 100.0],
            "next_entry_amount": [1000.0, 1000.0],
        }
    )
    series, ledger = audit.strict_next_bar_portfolio(
        selected, next_bar, [pd.Timestamp("2024-01-02")], "BASE"
    )
    expected_filled = engine._net_return(
        pd.Series([10.0, 10.0]),
        pd.Series([11.0, 11.0]),
        pd.Series(pd.to_datetime(["2024-01-02", "2024-01-02"])),
        "BASE",
    )
    assert series.iloc[0] == pytest.approx(float(expected_filled.sum() / 3.0))
    assert ledger["next_bar_executable"].tolist() == [True, True, False]
    assert ledger["cash_slot"].tolist() == [False, False, True]


def test_next_bar_fill_must_still_respect_limit_buffer():
    selected = _selected()
    next_bar = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02"] * 3),
            "instrument": ["A", "B", "C"],
            "next_entry_open": [10.0, 11.95, 10.0],
            "next_entry_volume": [100.0] * 3,
            "next_entry_amount": [1000.0] * 3,
        }
    )
    _, ledger = audit.strict_next_bar_portfolio(
        selected, next_bar, [pd.Timestamp("2024-01-02")], "BASE"
    )
    assert ledger["next_bar_executable"].tolist() == [True, False, True]


def test_missing_exit_after_successful_next_bar_entry_is_hard_failure():
    selected = _selected()
    selected.loc[selected["instrument"].eq("B"), "exit_1000"] = float("nan")
    next_bar = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02"] * 3),
            "instrument": ["A", "B", "C"],
            "next_entry_open": [10.0] * 3,
            "next_entry_volume": [100.0] * 3,
            "next_entry_amount": [1000.0] * 3,
        }
    )
    with pytest.raises(RuntimeError, match="missing 10:00 exits"):
        audit.strict_next_bar_portfolio(
            selected, next_bar, [pd.Timestamp("2024-01-02")], "BASE"
        )
