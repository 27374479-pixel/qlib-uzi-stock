# V5 M06 — source-aligned recovery polarity representation

## Purpose

M06 adds **directional semantics** to the already frozen M05 one-session changes. It still does not assign `BEAR_RECOVERY_CONTEXT`, fit a score, choose thresholds, or inspect strategy returns.

The lower-volume source says bear-market opportunity appears only after deterioration settles and recovery begins; the same source asks the trader to review advance/decline participation, limit/failed-limit activity, board structure and the subsequent behavior of prior strong stocks. M04 separately represents whether strength is concentrated or broadening across industries.

M06 therefore fixes only which *direction* of each M05 change is source-aligned with repair/broadening. It does not decide how many dimensions must agree, how long agreement must persist, or what level is sufficient.

## Frozen directional map

A positive `aligned_delta_*` always means movement in the source-aligned repair/broadening direction:

- `advance_ratio`: higher;
- `decline_ratio`: lower;
- `limit_down_ratio`: lower;
- `seal_ratio`: higher;
- `broken_ratio`: lower;
- `multi_board_ratio`: higher;
- `prior_seal_mean_return`: higher;
- `prior_multi_board_mean_return`: higher;
- `positive_industry_ratio`: higher;
- `seal_industry_ratio`: higher;
- `first_board_industry_ratio`: higher;
- `multi_board_industry_ratio`: higher;
- `seal_hhi`: lower (less concentration / more dispersion);
- `first_board_hhi`: lower;
- `multi_board_hhi`: lower.

For each available M05 delta, M06 emits the oriented numeric delta plus a three-way sign `-1 / 0 / +1`. Missing upstream values remain missing and are never converted to neutral zero.

## Structural validation only

M06 may pass only if:

- dates remain one-per-session and ordered;
- each aligned delta equals the frozen M05 delta times its preregistered orientation exactly within floating tolerance;
- each sign equals the sign of the aligned delta;
- missing M05 deltas remain missing in both aligned value and sign;
- the first date remains missing for every one-session delta;
- changing future rows cannot alter already-computed historical polarity rows in the unit causality test.

## Prohibitions

M06 does **not** authorize:

- summing signs into a recovery score;
- majority-vote or all-of-N recovery rules;
- persistence windows;
- quantile/level thresholds;
- clustering;
- assigning bull/bear/recovery labels;
- opening W01 returns;
- modifying X02;
- portfolio combination, paper trading or live trading.

Any later mapping from these directional observations to `BEAR_RECOVERY_CONTEXT` requires a new preregistration and independent non-strategy-return validation concept.