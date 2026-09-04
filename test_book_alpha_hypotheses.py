from __future__ import annotations

import numpy as np
import pandas as pd

from baostock_csi800_membership_history import compress_intervals
from book_alpha_daily_screen import ScreenConfig, paired_difference
from book_alpha_daily_screen_v2 import enforce_universe_policy


def test_membership_intervals_never_backdate_changes() -> None:
    snapshots = pd.DataFrame(
        {
            "snapshot_date": pd.to_datetime([
                "2026-01-05", "2026-01-12", "2026-01-12", "2026-01-19",
            ]),
            "instrument": ["SH600000", "SH600000", "SZ000001", "SZ000001"],
        }
    )
    result = compress_intervals(snapshots, pd.Timestamp("2026-01-25"))
    sh = result.loc[result["instrument"].eq("SH600000")].iloc[0]
    sz = result.loc[result["instrument"].eq("SZ000001")].iloc[0]
    assert sh["start"] == pd.Timestamp("2026-01-05")
    # Absence is first observed on Jan-19, so deletion is not back-dated.
    assert sh["end"] == pd.Timestamp("2026-01-18")
    assert sz["start"] == pd.Timestamp("2026-01-12")
    assert sz["end"] == pd.Timestamp("2026-01-25")


def test_universe_policy_keeps_mainboard_chinext_only_after_120_sessions() -> None:
    frame = pd.DataFrame(
        {
            "instrument": ["SH600000", "SZ300001", "SH688001", "SZ000001"],
            "history_n": [120, 130, 300, 119],
        }
    )
    result, meta = enforce_universe_policy(frame)
    assert set(result["instrument"]) == {"SH600000", "SZ300001"}
    assert meta["removed_rows"] == 2


def _sample(values: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=len(values), freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "entry_filled": True,
            "return_1d": values,
        }
    )


def test_paired_difference_respects_negative_veto_direction() -> None:
    selected = _sample([-0.02, -0.01, -0.03, -0.01, -0.02, -0.01, -0.02, -0.01, -0.03, -0.02])
    control = _sample([0.01, 0.00, 0.02, 0.01, 0.00, 0.01, 0.02, 0.00, 0.01, 0.02])
    config = ScreenConfig(bootstrap_samples=200)
    result = paired_difference(selected, control, 1, -1, config)
    assert result["selected_minus_control"] < 0
    assert result["expected_signed_difference"] > 0
    low, high = result["bootstrap95_expected_signed_difference"]
    assert low is not None and high is not None
    assert low > 0
