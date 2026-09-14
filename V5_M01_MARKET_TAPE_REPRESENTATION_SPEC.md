# V5 M01 — source-grounded market-tape representation

## Purpose

M01 is a **representation audit**, not an alpha test and not a market-regime classifier.  Its purpose is to build the smallest point-in-time market-state vector that can be defended directly from the user-supplied 48-trader books, without reverse-engineering a `bull / bear / recovery / retreat` threshold from strategy P&L.

This is a prerequisite for the W01 weak-market sleeve.  W01 is frozen deferred because the book gives a concrete `3–7 sessions / 20%–25% / first post-top` pullback structure but does not machine-define the bear-market state.  M01 may improve representation evidence, but **cannot by itself authorize W01 returns**.

## Source evidence

### Lower volume, PDF pp.71–73/227 (printed pp.40–42)

The text treats the market as cyclical rather than permanently tradable.  It explicitly describes bear-market opportunity as changing through a decline/recovery process and says that opportunity should be observed patiently rather than assumed from a large decline alone.  This supports representing the market as a changing state, but does **not** provide numeric boundaries for the states.

### Lower volume, PDF pp.100–103/227 (printed pp.69–72)

The short-term review discussion says market / main-board sentiment matters and describes daily review as collecting market-structure data such as limit-up / failed-limit-up activity, consecutive-board counts, and the subsequent performance of prior strong stocks.  These are observable tape variables available at the completed daily close.

### Upper volume, total-leader traits

The upper-volume leader list says strong leaders often start before the end of an index adjustment.  This reinforces that market context and leader structure interact, but again does not give a numeric regime threshold.

## Frozen M01 observables

M01 records only completed-close information and one-session lagged identity flags.  It does not create a score or threshold.

Per trading date:

1. `universe_n` — point-in-time CSI800 membership rows with valid daily bars.
2. `advance_count`, `decline_count`, `flat_count` — same-day close versus preclose sign counts.
3. `breadth` — `(advance_count - decline_count) / universe_n`; descriptive only.
4. `touch_count` — stocks whose daily high touched the inferred regular A-share upper limit.
5. `seal_count` — stocks closing at the inferred upper limit.
6. `broken_count` — touched upper limit but did not seal.
7. `broken_ratio` — `broken_count / max(touch_count, 1)`; descriptive only.
8. `limit_down_count` — stocks closing at the inferred lower limit.
9. `max_board_height` — maximum completed consecutive sealed-board height that day.
10. `multi_board_count` — number of rows with completed `board_height >= 2`.
11. `prior_seal_sample_n` and `prior_seal_mean_return` — today’s return of stocks that were sealed limit-up on their own immediately preceding valid row.
12. `prior_multi_board_sample_n` and `prior_multi_board_mean_return` — today’s return of stocks whose immediately preceding valid row had `board_height >= 2`.

No rolling window, no fitted weight, no future return, no index-MA rule, no breadth threshold and no `weak_market` boolean is part of M01.

## Structural validation only

M01 may return `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_MARKET_TAPE` only when all frozen accounting invariants hold:

- one row per date;
- `advance + decline + flat == universe_n`;
- `seal_count <= touch_count <= universe_n`;
- `broken_count == touch_count - seal_count`;
- `multi_board_count <= seal_count`;
- all count fields are nonnegative and bounded by `universe_n`;
- ratios are finite and within their arithmetic bounds;
- prior-winner sample sizes are bounded by `universe_n`;
- prior-winner means are finite whenever their sample size is positive;
- each source-named tape dimension exists on the historical panel;
- changing future rows cannot change an already-computed past date in the unit-level causality test.

The historical audit may report coverage, quantiles, correlations and year-by-year descriptive distributions.  Those are representation diagnostics only and **must not be used to choose thresholds in the same experiment**.

## Explicit prohibitions

M01 does not authorize:

- labeling a date `BULL`, `BEAR`, `RECOVERY`, `RETREAT`, `OPPORTUNITY_PRESENT`, or similar;
- choosing a threshold from X02 or W01 returns;
- changing X02;
- opening W01’s P&L screen;
- combining M01 with X02 into an all-weather portfolio;
- paper trading or live trading.

A future M02 economic/regime experiment requires a new preregistration commit and an independent target/validation concept that does not derive its labels from the strategy returns it is meant to gate.
