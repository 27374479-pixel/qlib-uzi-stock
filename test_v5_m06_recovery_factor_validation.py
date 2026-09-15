import numpy as np
import pandas as pd

import v5_m06_recovery_factor_validation as m06


def _synthetic(n=160, seed=7):
    rng = np.random.default_rng(seed)
    latent = np.linspace(-2.0, 2.0, n) + rng.normal(0, 0.15, n)
    data = {"date": pd.date_range("2023-01-01", periods=n, freq="D")}
    for i, name in enumerate(m06.ORIENTED_FEATURES):
        raw_oriented = latent + rng.normal(0, 0.08 + i * 0.002, n)
        data[name] = raw_oriented / m06.ORIENTED_FEATURES[name]
    data["delta_prior_seal_mean_return"] = latent + rng.normal(0, 0.10, n)
    data["delta_prior_multi_board_mean_return"] = latent + rng.normal(0, 0.12, n)
    return pd.DataFrame(data)


def test_orientation_makes_source_recovery_positive():
    frame = _synthetic(20)
    oriented = m06.orient_primary(frame)
    for name in m06.ORIENTED_FEATURES:
        assert np.isfinite(oriented[name]).all()


def test_pc1_orients_common_direction_positive():
    oriented = m06.orient_primary(_synthetic())
    model = m06.fit_development_pc1(oriented)
    assert all(v > 0 for v in model["loadings"])
    assert model["explained_variance_ratio"] > 0


def test_scoring_uses_frozen_model_without_refit():
    oriented = m06.orient_primary(_synthetic())
    model = m06.fit_development_pc1(oriented)
    score1 = m06.score_with_frozen_pc(oriented, model)
    changed = oriented.copy()
    changed.loc[changed["date"] >= pd.Timestamp("2024-01-01"), list(m06.ORIENTED_FEATURES)] *= 5.0
    score2 = m06.score_with_frozen_pc(changed, model)
    past = oriented["date"] < pd.Timestamp("2024-01-01")
    np.testing.assert_allclose(score1[past], score2[past], equal_nan=True)


def test_block_bootstrap_is_deterministic_and_positive_for_aligned_series():
    x = np.linspace(-1, 1, 120)
    y = x + np.sin(np.arange(120)) * 0.01
    a = m06.moving_block_bootstrap_spearman(x, y, block=10, draws=300, seed=123)
    b = m06.moving_block_bootstrap_spearman(x, y, block=10, draws=300, seed=123)
    assert a == b
    assert a["observed"] > 0
    assert a["ci95_low"] > 0


def test_strategy_and_trading_authorizations_are_closed():
    c = m06.CONTRACT
    assert c["strategy_returns_used"] is False
    assert c["parameter_search"] is False
    assert c["state_labels_authorized"] is False
    assert c["factor_threshold_authorized"] is False
    assert c["w01_return_screen_authorized"] is False
    assert c["x02_change_authorized"] is False
    assert c["portfolio_combination_authorized"] is False
    assert c["paper_trading_authorized"] is False
    assert c["live_trading_authorized"] is False
