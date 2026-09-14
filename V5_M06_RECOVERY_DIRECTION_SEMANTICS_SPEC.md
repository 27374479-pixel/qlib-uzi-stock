# V5 M06 — source-grounded recovery-direction semantics

## Purpose

M06 adds **directional meaning** to the one-session changes already frozen by M05. It is a descriptive representation audit only. It does not assign market-cycle states, does not define a recovery score, and does not inspect X02/W01 returns.

The lower-volume source describes bear-market opportunity as appearing when deterioration settles and recovery begins. Its review discussion separately names advance/decline participation, limit/failed-limit activity, board structure and treatment of prior strong stocks as market-sentiment observations. M04 additionally provides the source-grounded broadening/concentration layer motivated by the book's description of a broad opportunity set rather than one isolated hotspot.

M05 already freezes the causal one-completed-session first difference for these observables. M06 asks only: **for each individual dimension, does today's one-session change point in the economically improving, deteriorating, unchanged, or unavailable direction?**

## Frozen polarity map

No polarity is learned from returns. The following mapping is frozen before the historical audit.

Higher one-session change is interpreted as improvement for:

- `advance_ratio`
- `seal_ratio`
- `multi_board_ratio`
- `prior_seal_mean_return`
- `prior_multi_board_mean_return`
- `positive_industry_ratio`
- `seal_industry_ratio`
- `first_board_industry_ratio`
- `multi_board_industry_ratio`

Lower one-session change is interpreted as improvement for:

- `decline_ratio`
- `limit_down_ratio`
- `broken_ratio`
- `seal_hhi`
- `first_board_hhi`
- `multi_board_hhi`

For each M05 `delta_*` value:

- positive after applying the frozen polarity -> `+1` (`IMPROVING`);
- negative -> `-1` (`DETERIORATING`);
- exactly zero -> `0` (`UNCHANGED`);
- missing -> missing (`UNAVAILABLE`).

Zero is the arithmetic neutral point of a first difference, not an optimized threshold.

## Descriptive agreement counts

Per completed date M06 may report only:

- number of improving dimensions;
- number of deteriorating dimensions;
- number of unchanged dimensions;
- number of available dimensions;
- number of unavailable dimensions.

These counts are **not** a recovery score and no count threshold may define `BEAR_RECOVERY_CONTEXT` inside M06.

## Structural validation

M06 can return `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_DIRECTION_SEMANTICS` only if:

- the polarity map covers every frozen M05 level exactly once;
- every available direction is one of `-1, 0, +1`;
- improving + deteriorating + unchanged equals available;
- available + unavailable equals the frozen dimension count;
- missing M05 deltas remain unavailable rather than being imputed;
- the first date does not fabricate direction values from unavailable first differences;
- there is one output row per date;
- historical coverage is reported without using the distribution to choose a threshold.

## Explicit prohibitions

M06 does not authorize:

- `BEAR_DECLINE_CONTEXT`, `BEAR_RECOVERY_CONTEXT`, `BULL_BROADENING_CONTEXT`, or any date-state label;
- an aggregate recovery score, weighted or unweighted;
- a minimum number/fraction of improving dimensions;
- persistence or consecutive-day rules;
- quantile-based thresholds;
- W01 return screening;
- X02 changes;
- portfolio combination;
- paper trading or live trading.

Any future state rule requires a new preregistration with independent non-strategy-return justification for the required dimensions, agreement rule, persistence and ambiguity handling.