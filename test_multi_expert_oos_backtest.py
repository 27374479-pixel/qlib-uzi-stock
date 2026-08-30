import math

from multi_expert_oos_backtest import Config, EXPERT_FEATURES, router_weights


def test_router_is_equal_weight_before_history_matures():
    config = Config(router_min_history=6)
    history = {name: [0.1] * 5 for name in EXPERT_FEATURES}

    weights = router_weights(history, config)

    assert set(weights) == set(EXPERT_FEATURES)
    assert all(math.isclose(value, 1 / 3) for value in weights.values())


def test_router_weights_are_bounded_and_sum_to_one():
    config = Config(router_min_history=2, router_floor=0.10)
    history = {
        "reversal": [-0.20, -0.10],
        "trend": [0.00, 0.02],
        "defensive": [0.20, 0.30],
    }

    weights = router_weights(history, config)

    assert math.isclose(sum(weights.values()), 1.0)
    assert min(weights.values()) >= config.router_floor
    assert weights["defensive"] > weights["trend"] > weights["reversal"]
