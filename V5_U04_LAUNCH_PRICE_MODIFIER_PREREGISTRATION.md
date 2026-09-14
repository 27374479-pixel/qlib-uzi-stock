# V5 U04 preregistration — book-grounded <10 CNY launch-price modifier

## Source claim

Primary source: user-supplied `48位游资-上册`, market-total-leader trait list.

The list explicitly includes both:

- `三连板启动`;
- `启动价位低于10元，可炒作空间大`.

The numerical threshold **10 CNY** comes from the source and is frozen exactly.  U04 does not search alternative price cutoffs.

The source does not provide a machine-ready definition of `启动价`.  U04 therefore declares one transparent operational proxy **before reading any U04 return result** rather than presenting the proxy as verbatim book text.

A secondary source convention from the supplied lower volume is used only for the recurring short-term primary horizon: roughly next-day / 1–2 trading-day holding rhythm.  It does not create the U04 price hypothesis.

## Narrow economic question

Among otherwise comparable, accessible **three-board starts**, does the book's `<10 CNY` launch-price characteristic provide a persistent **relative** short-horizon advantage over starts at `>=10 CNY`?

This is a modifier test, not a standalone alpha test.  The book wording `可炒作空间大` motivates relative room/advantage; it does not state that every low-priced three-board stock must have positive absolute expectancy.

## Frozen operationalization

For one instrument in completed daily rows, sorted by trading date:

1. **three-board start event:** current row is sealed with `board_height == 3`, immediately previous row is sealed with `board_height == 2`, and row T-2 is sealed with `board_height == 1`;
2. **accessibility base:** all three board rows are not `one_word`, matching the source's separate `板板换手，每天都能参与进去` context while holding accessibility identical in selected/control;
3. **launch-reference price:** the `preclose` on the **first-board row** (T-2), i.e. the nominal close immediately before the three-board sequence began.  This is U04's operational proxy for `启动价`;
4. **selected / low-launch-price:** `launch_reference_price < 10.00` CNY;
5. **control / high-launch-price:** same frozen three-board/accessibility base with `launch_reference_price >= 10.00` CNY.

Selected and control must be mutually exclusive.  The `<10` boundary is strict because the source says `低于10元`.

### Price-field integrity

The 10-CNY claim is a **nominal price** claim.  U04 must use the persisted BaoStock nominal `preclose` field used by the repository's daily price-limit logic, not a normalized price rank or a fitted adjusted-price proxy.  Rows with missing, non-finite or non-positive launch-reference prices are in neither cohort.  U04 is technically invalid if the required nominal field is unavailable.

No later market outcome or U04 return may be used to redefine `launch_reference_price`.

## Causal execution convention

The signal event is known only after the third-board daily close.

- entry: next available trading row's open;
- if the next session is locked at the upper limit under the repository's existing point-in-time execution proxy, the entry is **unfilled**;
- no replacement security and no reweighting of an unfilled observation;
- primary holding horizon: **2 trading days** from entry;
- diagnostic horizons: 1 and 5 trading days only;
- round-trip cost: **0.36%**;
- no intraday fill assumption is introduced by U04.

## Frozen data partitions

- universe: point-in-time CSI800 membership, with the repository's existing tradability/ST/price-limit handling;
- research start: `2021-05-17`;
- development: `2021-05-17 .. 2023-12-31`;
- historical-later: `2024-01-01 .. 2026-09-03`;
- bootstrap samples: `5000`;
- random seed: `20260914`.

The 2024+ partition is historical-later, not pristine future OOS.

## Primary comparison and gate

The primary statistic is the same-date selected-minus-control difference in **2-day net return after costs**.

For **each** historical partition, coverage must first satisfy:

- selected executable observations >= **30**;
- selected active dates >= **20**;
- control executable observations >= **30**;
- control active dates >= **20**;
- dates on which both selected and control have executable observations >= **15**.

If either partition misses any coverage gate, status is `INSUFFICIENT`.

If coverage is sufficient, U04 qualifies only when **both** partitions satisfy all of:

1. paired selected-minus-control 2-day mean difference > 0;
2. date-bootstrap 95% confidence interval lower bound for that paired difference > 0.

There is deliberately **no absolute-profit requirement** in the U04 modifier gate.  If the relative gate passes while selected absolute expectancy is negative, the result may still be called `QUALIFIED_AS_RELATIVE_MODIFIER_ONLY`, but it can only modify a separately validated profitable strategy.  It can never authorize standalone trading.

Any other result is `REJECTED`.

## Diagnostics that cannot change the verdict

U04 may report, but must not optimize on:

- selected/control absolute mean and median net returns;
- selected/control market excess;
- fill rate;
- 1-day and 5-day horizons;
- calendar-year splits;
- weak/non-weak market splits.

These are descriptive only after the frozen 2-day gate is applied.

## Existing historical work does not define U04

The repository contains an older generic `price-under-10` diagnostic on a broader `core` population.  U04 is **not** a retest selected from that diagnostic's outcome: it tests the source-specific concept of **launch price at a three-board start**, with a frozen pre-sequence nominal-price definition and matched three-board accessibility context.  The old generic price diagnostic is not an input to U04's gate and cannot be used to alter this contract after results.

## Prohibited rescue

After the first U04 result is read, do not:

- move 10 CNY to another price threshold;
- redefine launch price as current close/open, first-board close, VWAP, market-cap rank or a price quantile;
- change three boards to two/four boards;
- add/remove the accessibility condition to improve the outcome;
- change the 2-day primary horizon or 0.36% cost;
- subset by market regime, year, industry or theme to rescue a failure;
- combine U04 with X02 or another sleeve to hide a failed standalone test.

A materially different rule requires a new source-grounded experiment and a new preregistration committed before its returns are read.

## Authorization boundary

Even a pass means only `QUALIFIED_AS_RELATIVE_MODIFIER_ONLY`.

U04 never directly authorizes:

- a standalone trading signal;
- a new all-weather sleeve;
- X02 retuning or gating changes;
- portfolio combination;
- paper trading;
- live trading.
