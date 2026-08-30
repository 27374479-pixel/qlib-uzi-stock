import pandas as pd

import long_uzi_state_backtest as model


def _minutes():
    rows = []
    for date, base in [(pd.Timestamp("2024-01-01"), 10.0), (pd.Timestamp("2024-01-02"), 10.5), (pd.Timestamp("2024-01-03"), 10.8)]:
        for offset, price in enumerate([base, base * 1.01, base * 1.02, base * 1.03]):
            timestamp = date + pd.Timedelta(hours=9, minutes=35 + offset * 5)
            rows.append(
                {
                    "instrument": "SH600000",
                    "datetime": timestamp,
                    "open": price,
                    "high": price * 1.002,
                    "low": price * 0.998,
                    "close": price,
                    "volume": 1000.0,
                    "amount": 10000.0,
                }
            )
    return pd.DataFrame(rows)


def test_target_exposure_is_predeclared_and_bounded():
    values = [model._target_exposure(state) for state in ["ice", "weak", "neutral", "strong", "climax"]]
    assert values == [0.0, 0.12, 0.35, 0.60, 0.20]
    assert all(0.0 <= value <= 1.0 for value in values)


def test_outcome_entry_is_strictly_after_cutoff():
    minutes = _minutes()
    day_groups = {
        date: group.sort_values("datetime").reset_index(drop=True)
        for date, group in minutes.groupby(minutes["datetime"].dt.normalize())
    }
    dates = sorted(day_groups)
    result = model._outcomes(
        day_groups,
        dates[0],
        3,
        previous_close=9.9,
        ratio=0.10,
        trading_dates=dates,
        date_positions={date: index for index, date in enumerate(dates)},
        open_cost=0.0,
        close_cost=0.0,
    )
    assert result["entry_filled"] is True
    assert result["entry_datetime"] == dates[0] + pd.Timedelta(hours=9, minutes=50)
    assert result["entry_datetime"] > dates[0] + pd.Timedelta(hours=9, minutes=45)


def test_market_state_uses_only_named_prior_and_current_columns():
    prior = pd.DataFrame(
        {
            "prior_breadth": [-0.3, 0.1, 0.4],
            "prior_money_effect_5d": [-0.01, 0.003, 0.005],
        }
    )
    current = pd.DataFrame(
        {
            "market_breadth": [-0.2, 0.25, 0.6],
            "market_median": [-0.01, 0.004, 0.015],
            "market_broken_ratio": [0.2, 0.1, 0.6],
        }
    )
    assert model._market_state(prior, current).tolist() == ["weak", "strong", "climax"]


def test_future_outcome_columns_cannot_change_signal_features():
    rows = []
    for index in range(8):
        rows.append(
            {
                "instrument": f"SH6000{index:02d}",
                "signal_date": pd.Timestamp("2024-06-03"),
                "cutoff": "10:15",
                "signal_datetime": pd.Timestamp("2024-06-03 10:15"),
                "industry_code": "A" if index < 4 else "B",
                "intraday_return": 0.02 + index * 0.001 if index < 4 else -0.01,
                "prior_ret10": 0.05 if index < 4 else -0.01,
                "recovery_from_low": 0.03 if index < 4 else 0.0,
                "amount_ratio_asof": 1.0,
                "prior_limit_up5": 1 if index < 4 else 0,
                "from_open": 0.02 if index < 4 else -0.01,
                "from_high": -0.01 if index < 4 else -0.02,
                "late_momentum_30m": 0.003 if index < 4 else -0.001,
                "gap_to_upper": -0.01,
                "locked_upper": False,
                "touched_upper": False,
                "broken_upper": False,
                "current_close": 10.0,
                "current_high": 10.1,
                "current_low": 9.9,
                "entry_filled": True,
                "dynamic_return": 0.25,
                "return_1d": -0.25,
            }
        )
    asof = pd.DataFrame(rows)
    market = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-06-02")],
            "breadth": [0.1],
            "money_effect_5d": [0.003],
            "ret_median": [0.002],
            "universe_n": [8],
        }
    ).set_index("date")
    first = model._score_snapshots(asof, market)
    changed = asof.copy()
    changed["entry_filled"] = False
    changed["dynamic_return"] = -999.0
    changed["return_1d"] = 999.0
    second = model._score_snapshots(changed, market)
    columns = ["trigger", "score", "market_state", "target_exposure", "mode"]
    pd.testing.assert_frame_equal(first[columns], second[columns])


def test_dynamic_exit_uses_next_open_after_observation():
    day = pd.DataFrame(
        [
            {
                "datetime": pd.Timestamp("2024-01-03 09:35"),
                "open": 9.80,
                "high": 9.90,
                "low": 9.70,
                "close": 9.10,
            },
            {
                "datetime": pd.Timestamp("2024-01-03 09:40"),
                "open": 9.20,
                "high": 9.30,
                "low": 9.10,
                "close": 9.25,
            },
        ]
    )
    price, reason = model._exit_price_after_first_bar(day, previous_close=10.0, ratio=0.10)
    assert price == 9.20
    assert reason == "next_bar_open_after_observation"


def test_daily_limit_state_distinguishes_sealed_from_one_word():
    rows = [
        {
            "instrument": "SH600000",
            "datetime": pd.Timestamp("2024-01-02 09:35"),
            "open": 10.0,
            "high": 10.0,
            "low": 10.0,
            "close": 10.0,
            "volume": 1000.0,
            "amount": 10000.0,
        },
        {
            "instrument": "SH600000",
            "datetime": pd.Timestamp("2024-01-03 09:35"),
            "open": 10.2,
            "high": 10.8,
            "low": 10.2,
            "close": 10.8,
            "volume": 1000.0,
            "amount": 10500.0,
        },
        {
            "instrument": "SH600000",
            "datetime": pd.Timestamp("2024-01-03 15:00"),
            "open": 10.8,
            "high": 11.0,
            "low": 10.7,
            "close": 11.0,
            "volume": 1000.0,
            "amount": 10900.0,
        },
    ]
    daily = model._daily_features(pd.DataFrame(rows), min_daily_bars=1)
    event = daily.iloc[-1]
    assert bool(event["limit_touched"]) is True
    assert bool(event["limit_locked"]) is True
    assert bool(event["limit_one_word"]) is False
    assert bool(event["limit_broken"]) is False
