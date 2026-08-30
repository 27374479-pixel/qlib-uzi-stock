import pandas as pd

from medium_term_direction_backtest import _stats, cohort_dates


def test_cohort_dates_leave_forward_window_and_are_spaced():
    calendar = pd.bdate_range("2024-01-01", periods=100)
    dates = cohort_dates(calendar, "2024-01-01", "2024-12-31", spacing=30, offset=0, forward_days=31)
    positions = [calendar.get_loc(date) for date in dates]
    assert all(right - left == 30 for left, right in zip(positions, positions[1:]))
    assert positions[-1] <= len(calendar) - 32


def test_direction_accuracy_is_computed_by_date_not_only_by_stock():
    frame = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-02", "2024-02-20", "2024-02-20"],
            "return_20d": [0.10, -0.02, -0.03, -0.01],
            "return_30d": [0.20, 0.01, -0.04, -0.02],
        }
    )
    stats = _stats(frame)
    assert stats["20d"]["portfolio_direction_accuracy"] == 0.5
    assert stats["30d"]["portfolio_direction_accuracy"] == 0.5
    assert stats["both_horizons_up_accuracy"] == 0.5
