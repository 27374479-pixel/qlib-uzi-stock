import pandas as pd

from intraday_candidate_backtest import (
    BacktestConfig,
    _comparison_report,
    executable_prices,
    minute_features_asof,
    score_intraday_candidates,
)


def _minutes() -> pd.DataFrame:
    rows = []
    for day, base in (("2026-07-01", 10.0), ("2026-07-02", 10.5), ("2026-07-03", 11.0)):
        for clock, bump in (("09:35", 0.00), ("13:30", 0.01), ("14:00", 0.02), ("14:45", 0.03), ("15:00", 0.04)):
            price = base * (1 + bump)
            rows.append(
                {
                    "datetime": pd.Timestamp(f"{day} {clock}:00"),
                    "open": price,
                    "close": price,
                    "high": price,
                    "low": price,
                    "amount": 30_000_000,
                }
            )
    return pd.DataFrame(rows)


def test_1400_features_do_not_change_when_future_bars_change():
    original = _minutes()
    changed = original.copy()
    future = changed["datetime"] > pd.Timestamp("2026-07-02 14:00:00")
    changed.loc[future, ["open", "close", "high", "low"]] = 999.0

    left = minute_features_asof(original, pd.Timestamp("2026-07-02"))
    right = minute_features_asof(changed, pd.Timestamp("2026-07-02"))

    assert left == right


def test_entry_uses_first_bar_after_decision_window():
    frame = _minutes()
    dates = [pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-02"), pd.Timestamp("2026-07-03")]

    prices = executable_prices(frame, pd.Timestamp("2026-07-02"), dates)

    expected_entry = frame.loc[frame["datetime"] == pd.Timestamp("2026-07-02 14:45:00"), "open"].iloc[0]
    expected_exit = frame.loc[frame["datetime"] == pd.Timestamp("2026-07-03 09:35:00"), "open"].iloc[0]
    assert prices["entry"] == expected_entry
    assert prices["exit_1d"] == expected_exit


def test_intraday_filter_rejects_overheated_stock():
    frame = pd.DataFrame(
        {
            "prior_score": [0.9, 0.8],
            "intraday_return": [0.04, 0.09],
            "from_open": [0.02, 0.08],
            "from_high": [-0.01, -0.01],
            "late_momentum_30m": [0.01, 0.03],
            "amount_to_signal": [100_000_000, 200_000_000],
            "amount_ratio": [1.2, 2.0],
        }
    )

    result = score_intraday_candidates(frame, BacktestConfig())

    assert bool(result.iloc[0]["eligible_intraday"])
    assert not bool(result.iloc[1]["eligible_intraday"])


def test_comparison_report_uses_same_date_broad_baseline():
    portfolios = pd.DataFrame(
        [
            {"date": "2026-07-01", "strategy": "broad_candidates", "return_1d": 0.01, "return_5d": 0.02},
            {"date": "2026-07-01", "strategy": "intraday_top", "return_1d": 0.03, "return_5d": 0.01},
            {"date": "2026-07-02", "strategy": "broad_candidates", "return_1d": -0.01, "return_5d": 0.00},
            {"date": "2026-07-02", "strategy": "intraday_top", "return_1d": 0.00, "return_5d": 0.02},
        ]
    )

    report = _comparison_report(portfolios)

    assert report["intraday_top"]["return_1d_excess_vs_broad"]["mean"] == 0.015
