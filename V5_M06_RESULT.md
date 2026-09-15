# V5 M06 frozen result — common recovery factor

## Outcome

**Status:** `NOT_SUPPORTED_AS_COMMON_RECOVERY_FACTOR`

M06 was preregistered before the historical run. The failure is frozen and may not be rescued by dropping features, changing signs, changing the split, changing the PCA dimension, changing bootstrap settings, or substituting validators.

## One-shot validation

GitHub Actions run: `34926850043`

- unit tests: **5 passed**;
- development rows used to fit PC1: **640**;
- PC1 explained variance ratio: **0.3705283**;
- artifact: `v5-m06-recovery-factor-results`;
- artifact id: `10380445614`;
- ZIP SHA-256: `911fd489360d1198cd31609dab9f4b303ffe113c04029e5f7c6852a07baee7d1`.

The preregistered all-positive-loading gate failed. Eleven of the thirteen source-oriented loadings were positive, but two were negative:

- `delta_multi_board_industry_ratio`: **-0.0036723**;
- `delta_multi_board_hhi`: **-0.0113683**.

Therefore the frozen common-factor gate fails even though the negative loadings are numerically small.

## Reserved non-strategy validators

The reserved prior-strong-stock behavior validators were supportive in both periods:

- development `delta_prior_seal_mean_return`: Spearman **0.3002**, 95% block-bootstrap CI **[0.2029, 0.4010]**;
- development `delta_prior_multi_board_mean_return`: **0.2093**, CI **[0.0271, 0.3870]**;
- historical-later `delta_prior_seal_mean_return`: **0.4006**, CI **[0.2979, 0.4971]**;
- historical-later `delta_prior_multi_board_mean_return`: **0.2971**, CI **[0.1350, 0.4272]**.

These positive validator results do not override the preregistered loading failure.

## Interpretation boundary

M06 rejects the hypothesis that **all thirteen** frozen source-oriented market dimensions belong to one common recovery factor under the preregistered definition. It does not prove which dimension is wrong or whether multi-board breadth/concentration belongs to a later stage.

Any attempt to separate an initial-recovery component from a later leadership-maturation component must first return to the books and be preregistered as a new experiment. It may not be justified merely by the two negative loadings observed here.

No market-state labels, factor threshold, W01 return screen, X02 change, portfolio combination, paper trading or live trading are authorized.