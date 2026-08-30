import pandas as pd

from yangjia_public_text_backtest import (
    BookConfig,
    PHASE_STRONG,
    PHASE_WEAK_LATE,
    PHASE_WEAK_MIDDLE,
    _phase_from_sentiment,
    public_text_target,
)


def test_weak_middle_and_late_are_distinguished_by_repair():
    config = BookConfig()
    weak_middle = {
        "sentiment_score": 0.30,
        "advance_ratio": 0.25,
        "median_ret_20": -0.20,
        "weak_ratio": 0.50,
        "top_decile_ret_5": -0.02,
    }
    assert _phase_from_sentiment(weak_middle, [0.45, 0.42, 0.38, 0.34, 0.31], config) == PHASE_WEAK_MIDDLE

    weak_late = {
        "sentiment_score": 0.38,
        "advance_ratio": 0.50,
        "median_ret_20": -0.20,
        "weak_ratio": 0.40,
        "top_decile_ret_5": 0.05,
    }
    assert _phase_from_sentiment(weak_late, [0.31, 0.30, 0.31, 0.32, 0.34], config) == PHASE_WEAK_LATE


def test_strong_phase_is_available_without_future_data():
    sentiment = {"sentiment_score": 0.75, "advance_ratio": 0.60}
    assert _phase_from_sentiment(sentiment, [0.50, 0.55], BookConfig()) == PHASE_STRONG


def test_public_text_target_starts_new_names_at_half_unit():
    frame = pd.DataFrame(
        {"confirmation": [False, True]},
        index=["SH600000", "SH600001"],
    )
    target = public_text_target(
        ["SH600000", "SH600001"],
        PHASE_STRONG,
        1.0,
        frame,
        {"SH600001": 0.5},
    )
    assert target["SH600000"] == 0.25
    assert target["SH600001"] == 0.50
    assert sum(target.values()) <= 1.0
