# V5 M05 — source-grounded recovery-dynamics representation

## Purpose

M05 builds a **descriptive market-recovery dynamics layer** over the already frozen M01 market tape and M04 cross-industry dispersion representations. It does not classify dates as bear/recovery/bull and does not inspect strategy returns.

The supplied lower-volume source describes bear-market opportunity as appearing only after deterioration settles and recovery begins, rather than because price has simply fallen a lot. A separate review passage explicitly says daily market review should include advance/decline balance, limit-up/limit-down and failed-limit activity, consecutive-board structure, and the subsequent performance of prior strong stocks. M01 and M04 already provide causal raw levels for those concepts.

M05 therefore asks only:

> Can the **direction of change** in those source-grounded market-tape dimensions be represented causally and coherently, without inventing a recovery threshold?

## Source grounding

### Lower volume PDF pp.71–73/227

The bear-market discussion says that while the market is still repeatedly falling, the appropriate action is to wait; opportunity appears when a decline settles and recovery starts. It also warns that a large prior decline by itself is not sufficient evidence.

This supports observing **change in deterioration/recovery pressure**, but does not specify a numeric threshold, number of sessions, or deterministic classifier.

### Lower volume PDF pp.100–103/227

The review discussion explicitly names market data such as advancing/declining participation, limit-up/limit-down balance, failed-limit activity, consecutive-board counts, and performance of prior limit-up / prior multi-board stocks as market-sentiment information.

M05 uses only transformations of M01/M04 source-grounded fields.

## Frozen M05 levels

M05 joins M01 and M04 by completed trading date and freezes the following normalized levels:

- `advance_ratio = advance_count / universe_n`
- `decline_ratio = decline_count / universe_n`
- `limit_down_ratio = limit_down_count / universe_n`
- `seal_ratio = seal_count / universe_n`
- `broken_ratio` from M01
- `multi_board_ratio = multi_board_count / universe_n`
- `prior_seal_mean_return` from M01
- `prior_multi_board_mean_return` from M01
- `positive_industry_ratio` from M04
- `seal_industry_ratio = seal_industry_n / known_industry_n`
- `first_board_industry_ratio = first_board_industry_n / known_industry_n`
- `multi_board_industry_ratio = multi_board_industry_n / known_industry_n`
- `seal_hhi`, `first_board_hhi`, `multi_board_hhi` from M04

## Frozen M05 changes

For each frozen level above, M05 records the **one completed-session first difference** (`current - prior`). One-session differencing is used because it is the smallest causal change observable and introduces no fitted lookback window.

Examples:

- falling `delta_decline_ratio` is descriptively consistent with less broad deterioration;
- falling `delta_limit_down_ratio` is descriptively consistent with less severe downside pressure;
- rising `delta_prior_seal_mean_return` is descriptively consistent with improving treatment of prior strong stocks;
- rising `delta_positive_industry_ratio` is descriptively consistent with broader industry participation;
- falling HHI is descriptively consistent with less concentrated leadership.

These interpretations are **not** a state classifier. M05 does not require any sign combination to be true.

## Missingness rule

`prior_seal_mean_return` and `prior_multi_board_mean_return` remain missing when the corresponding prior-strong-stock sample is absent. M05 does not fill missing observations with zero, because `no sample` is not equivalent to `zero return`.

Their first differences are present only when both adjacent level observations are present.

## Structural validation

M05 may return `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_RECOVERY_DYNAMICS` only if:

- M01 and M04 dates align one-to-one;
- there is one output row per date;
- all ratio/HHI levels remain finite and in `[0,1]`;
- bounded ratio/HHI first differences remain in `[-1,1]` whenever present;
- prior-strong-stock return levels/differences are finite whenever present;
- first-row differences are missing rather than fabricated;
- changing a future input row cannot change already-computed past output rows.

## Explicit prohibitions

M05 does not authorize:

- a `BEAR_RECOVERY_CONTEXT` date label;
- a recovery score or weighted composite;
- selecting a minimum number of improving dimensions;
- choosing thresholds from M05 historical quantiles;
- choosing persistence/lookback windows from X02 or W01 returns;
- opening W01 P&L;
- changing X02;
- portfolio combination;
- paper or live deployment.

A future mapping experiment must be separately preregistered and must justify its boundaries/validation independently of the strategy returns it is intended to gate.
