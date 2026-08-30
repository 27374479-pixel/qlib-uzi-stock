import numpy as np
import pandas as pd

from enriched_factor_backtest import style_neutralize_score


def test_style_neutralization_removes_size_volatility_and_industry_means():
    rng = np.random.default_rng(42)
    n = 240
    industry = np.repeat(["A", "B", "C"], n // 3)
    size = rng.normal(size=n)
    volatility = rng.normal(size=n)
    industry_effect = pd.Series(industry).map({"A": -1.0, "B": 0.3, "C": 1.2}).to_numpy()
    score = 2.0 * size - 1.5 * volatility + industry_effect + rng.normal(scale=0.05, size=n)
    index = pd.Index([f"s{i:03d}" for i in range(n)], name="instrument")
    frame = pd.DataFrame(
        {
            "log_float_market_cap": size,
            "vol_60": volatility,
            "industry_code": industry,
        },
        index=index,
    )

    neutral = style_neutralize_score(pd.Series(score, index=index), frame)

    assert abs(neutral.corr(frame["log_float_market_cap"], method="spearman")) < 0.05
    assert abs(neutral.corr(frame["vol_60"], method="spearman")) < 0.05
    assert neutral.groupby(frame["industry_code"]).mean().max() - neutral.groupby(frame["industry_code"]).mean().min() < 0.03
