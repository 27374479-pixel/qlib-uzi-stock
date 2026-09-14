# V5 Defensive Sleeve D01 Preregistration

This document freezes the D01 defensive-sleeve screen **before its first result is read**.

## Why a new sleeve

The preregistered V5 X02/cash regime router reduced 2021-2023 losses but did not create an all-weather strategy and materially damaged the 2024+ result. Its thresholds are therefore frozen as a failed research result and will not be tuned.

Existing weak-market challengers are not automatically promoted: the repository evidence registry rejects T+1 delayed reversal and overnight-information, while overnight-vs-intraday strength is only a retest candidate. D01 is a new, mechanism-distinct screen rather than a modification of X02.

## D01 mechanism

Hypothesis: among point-in-time CSI800 members already showing positive medium-term trend, the lower-realized-volatility names with momentum not manufactured by repeated limit hits should have more persistent post-entry returns than equally strong but high-volatility names.

This is intended as a possible defensive equity sleeve. It is not assumed to work; failure is a valid result.

## Frozen data and timing

- Point-in-time CSI800 membership and the repository's existing listing/ST/tradability policy.
- Signal uses completed daily data through signal date `T` only.
- Entry proxy is the next available trading session open (`T+1` open), with locked upper-limit sessions marked unfilled by the existing daily-screen infrastructure.
- Primary holding horizon is five trading sessions from entry open to the sixth available open (`return_5d`).
- One- and two-day horizons are descriptive diagnostics only.
- Fixed round-trip cost: **0.36%** for screening, deliberately conservative versus the repository's BASE daily screen.
- Historical evaluation begins 2021-05-17 to align with the persisted intraday research era.

## Frozen features

For each stock on signal date T:

- `daily_ret = close / preclose - 1`.
- `vol20 = rolling 20-session standard deviation of daily_ret`, minimum 15 observations.
- `vol20_rank = cross-sectional percentile rank of vol20` on T.
- `clean_mom60` is the existing 60-session compounded momentum that replaces limit-hit daily log returns with zero, minimum 40 observations.
- `clean_mom60_rank = cross-sectional percentile rank` on T.
- `hit_count20` is the existing trailing 20-session count of limit touches.

No market-regime variable is used in the D01 selector.

## Frozen selected and control cohorts

Common requirements:

- signal date >= 2021-05-17;
- `clean_mom60 > 0`;
- `clean_mom60_rank >= 0.70`;
- `hit_count20 <= 1`;
- valid `vol20_rank`;
- next-open entry is executable under the existing locked-limit policy.

Selected D01 cohort:

- `vol20_rank <= 0.35`.

High-volatility control cohort:

- `vol20_rank >= 0.65`.

The middle-volatility band is deliberately unused rather than searched.

## Primary qualification rule

D01 qualifies only for a later minute-level execution replay if **all** of the following are true at the fixed 5-day horizon:

1. Development/counterexample segment 2021-05-17 through 2023-12-31 has at least 100 selected observations and at least 40 active signal dates.
2. Historical-later segment 2024-01-01 onward has at least 100 selected observations and at least 40 active signal dates.
3. Selected mean return after the fixed 0.36% cost is positive in both segments.
4. Selected mean same-date market excess is positive in both segments.
5. Selected-minus-control paired-date mean return is positive in both segments.
6. The 95% date-bootstrap lower bound of selected-minus-control is above zero in both segments.

If any condition fails, D01 is rejected and its thresholds are not retuned.

## What a pass does and does not mean

A pass only permits a separately preregistered minute-level execution replay and correlation/complementarity test against frozen X02. It does not permit immediate combination, sizing optimization, or live trading.

The 2024+ market history has already been inspected elsewhere in this project, so this is historical development evidence, not pristine prospective OOS evidence.