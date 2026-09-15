# V5 M06 — non-P&L recovery-factor validation preregistration

## Purpose

M06 asks whether the source-grounded market dimensions already frozen in M05 contain a **common recovery direction** that is stable out of sample without using X02/W01 or any other strategy return.

This is not a regime classifier and not an alpha test. A pass would justify only a continuous descriptive recovery factor for later research; it would not define `BEAR_RECOVERY_CONTEXT`, open W01 P&L, or authorize routing/trading.

## Source basis

The supplied lower volume says bear-market opportunity appears only after deterioration settles and recovery begins. It separately treats advance/decline participation, limit/failed-limit activity, board structure and prior-strong-stock behavior as market-sentiment/review inputs. M04 additionally represents whether leadership is broadening or concentrated, consistent with the book's description of stronger markets as broader rather than dependent on one isolated hotspot.

## Frozen primary features

M06 uses only one-session M05 deltas. Each feature is oriented so **positive means source-consistent recovery**:

- `+ delta_advance_ratio`
- `- delta_decline_ratio`
- `- delta_limit_down_ratio`
- `+ delta_seal_ratio`
- `- delta_broken_ratio`
- `+ delta_multi_board_ratio`
- `+ delta_positive_industry_ratio`
- `+ delta_seal_industry_ratio`
- `+ delta_first_board_industry_ratio`
- `+ delta_multi_board_industry_ratio`
- `- delta_seal_hhi`
- `- delta_first_board_hhi`
- `- delta_multi_board_hhi`

The two lagged-strong-stock return deltas are deliberately **excluded from PCA fitting** and reserved as independent market-behavior validators:

- `delta_prior_seal_mean_return`
- `delta_prior_multi_board_mean_return`

Missing validator values remain missing and are never filled with zero.

## Frozen split and estimator

- development: through `2023-12-31`;
- historical-later: `2024-01-01` onward;
- standardization mean/std are fit on development only;
- factor estimator: first principal component from development-only SVD;
- PC sign is oriented so the sum of its 13 loadings is positive;
- historical-later scores use the frozen development means/std/loadings; no refit.

## Frozen falsification gates

M06 is `SUPPORTED_AS_COMMON_RECOVERY_FACTOR` only if all of the following hold:

1. every one of the 13 oriented PC1 loadings is strictly positive;
2. in development, factor score has positive Spearman correlation with each reserved validator, and each moving-block-bootstrap 95% lower confidence bound is > 0;
3. in historical-later, using the frozen development factor, the same two validator correlations are positive and each moving-block-bootstrap 95% lower confidence bound is > 0.

Bootstrap is frozen to 20-session moving blocks, 5,000 draws, seed `20260915`. This is inference only; no threshold search is allowed.

If any gate fails, the factor is rejected as a common recovery factor. No feature removal, sign change, alternate PCA count, alternate split, different block length or validator substitution may rescue M06. A new experiment would require a new preregistration.

## Explicit prohibitions

M06 does not authorize:

- bull/bear/recovery date labels;
- choosing a factor-score threshold;
- using strategy returns to orient or validate the factor;
- W01 return screening;
- X02 modification;
- portfolio combination;
- paper or live trading.
