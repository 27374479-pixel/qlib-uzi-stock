# V5 M01 frozen result — source-grounded market-tape representation

## Outcome

**Status:** `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_MARKET_TAPE`

This is a representation result only. It is **not** evidence that any market-tape threshold predicts returns, and it does not define `bull`, `bear`, `recovery`, `retreat`, `opportunity present`, or any other tradable regime.

## Frozen audit

Workflow run: `34814314114`

Historical point-in-time period:

- start: `2021-05-17`
- end: `2026-09-03`
- trading dates represented: `1,289`
- persisted daily parquet files fetched: `1,515`

Source-grounded tape dimensions were frozen before the historical audit:

- advance / decline / flat accounting and descriptive breadth;
- upper-limit touch, sealed-limit, failed-limit and lower-limit-close counts;
- maximum completed consecutive-board height and count of multi-board stocks;
- current-day return of stocks that were sealed on their immediately preceding valid row;
- current-day return of stocks whose immediately preceding valid row had board height >= 2.

All frozen structural invariants passed with **zero failures**. This includes duplicate-date checks, advance/decline/flat accounting, touch/seal/broken accounting, count bounds, ratio bounds/finite checks, multi-board <= sealed-board consistency, and prior-strong-stock sample/mean consistency.

Coverage for the two lagged strong-stock behavior fields was adequate for descriptive representation:

- `prior_seal_mean_return` available on `1,157 / 1,289` dates;
- `prior_multi_board_mean_return` available on `484 / 1,289` dates.

Unit suite: **6 passed**.

Artifact:

- name: `v5-m01-market-tape-results`
- artifact id: `10336226851`
- ZIP SHA-256: `241ad5057e57b429b21432be3e63416fd1d04fb3fcef58d8511bb3ffd3daa836`

## Interpretation boundary

M01 answers only this question:

> Can the market-context observables named or directly motivated by the supplied books be represented causally and coherently from completed daily information without using strategy returns?

For the frozen M01 vector, the answer is **yes**.

M01 intentionally did **not** inspect its descriptive quantiles/correlations to select thresholds. Any such threshold selection inside M01 would contaminate the next experiment.

## What remains unresolved

M01 does **not** resolve the most important missing W01 field: a machine-ready bear-market state. The books support market cycles and market-tape review, but the reviewed passages do not supply a deterministic mapping from the M01 vector to `bear / bull / recovery / retreat`.

Therefore the following remain false:

- regime-label authorization;
- alpha-evaluation authorization;
- W01 return-screen authorization;
- X02-change authorization;
- portfolio-combination authorization;
- paper-trading authorization;
- live-trading authorization.

## Next allowed research step

The next experiment may investigate whether the books provide enough **independent, non-P&L** evidence to define or validate a market-cycle state mapping over the frozen M01 tape. It must be preregistered separately before any strategy return is used.

Do not derive a bear-market threshold by maximizing W01 or X02 performance. If the source/independent validation target remains insufficient, the correct outcome is another defer and the R01 router stays `UNKNOWN -> CASH_ONLY`.
