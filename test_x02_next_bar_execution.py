from types import SimpleNamespace

import pandas as pd
import pytest

import audit_x02_next_bar_execution as audit


@pytest.fixture(autouse=True)
def _stub_legacy_engine(monkeypatch):
    """Keep these accounting tests independent of the full research stack."""
    def net_return(entry, exit_px, dates, cost_name):
        del dates, cost_name
        return exit_px / entry - 1.0

    monkeypatch.setattr(
        audit,
        "_engine",
        lambda: SimpleNamespace(_net_return=net_return),
    )


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
    assert series.iloc[0] == pytest.approx((0.10 + 0.10 + 0.0) / 3.0)
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


def test_frozen_active_day_must_keep_exactly_three_slots():
    selected = _selected().iloc[:2].copy()
    next_bar = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02"] * 2),
            "instrument": ["A", "B"],
            "next_entry_open": [10.0, 10.0],
            "next_entry_volume": [100.0, 100.0],
            "next_entry_amount": [1000.0, 1000.0],
        }
    )
    with pytest.raises(ValueError, match="exactly 3 slots"):
        audit.strict_next_bar_portfolio(
            selected, next_bar, [pd.Timestamp("2024-01-02")], "BASE"
        )


def test_execution_stats_are_period_local():
    ledger = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-12-29"] * 3 + ["2024-01-02"] * 3),
            "next_bar_executable": [True, True, False, True, False, False],
            "cash_slot": [False, False, True, False, True, True],
        }
    )
    _, later = audit._period_slice(
        pd.Series([0.0, 0.0], index=pd.to_datetime(["2023-12-29", "2024-01-02"])),
        ledger,
        pd.Timestamp("2024-01-01"),
        None,
    )
    stats = audit._execution_stats(later)
    assert stats == {
        "selection_rows": 3,
        "filled_rows": 1,
        "fill_rate": pytest.approx(1 / 3),
        "cash_slots": 2,
        "active_selection_days": 1,
        "days_with_any_unfilled_slot": 1,
    }


def test_empty_selection_returns_schema_safe_empty_ledger():
    selected = _selected().iloc[0:0].copy()
    series, ledger = audit.strict_next_bar_portfolio(
        selected,
        pd.DataFrame(),
        [pd.Timestamp("2024-01-02")],
        "BASE",
    )
    assert series.iloc[0] == 0.0
    assert ledger.empty
    assert "next_bar_executable" in ledger.columns
    assert "cash_slot" in ledger.columns
    assert audit._execution_stats(ledger)["selection_rows"] == 0


def test_duplicate_next_bar_records_are_hard_failure_in_accounting():
    selected = _selected()
    next_bar = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02"] * 3),
            "instrument": ["A", "B", "C"],
            "next_bar_rows": [1, 2, 1],
            "next_entry_open": [10.0] * 3,
            "next_entry_volume": [100.0] * 3,
            "next_entry_amount": [1000.0] * 3,
        }
    )
    with pytest.raises(RuntimeError, match="duplicate next-bar records"):
        audit.strict_next_bar_portfolio(
            selected, next_bar, [pd.Timestamp("2024-01-02")], "BASE"
        )
