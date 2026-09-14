# V5 T02 source review — trend-stock exit-rule prerequisite readiness

## Purpose

T02 is a **source-readiness gate**, not a return experiment. It asks whether the supplied lower-volume book gives enough machine-defensible detail to preregister an economic test of its trend-stock exit rules without inventing the prerequisite trend/main-rise state or execution details.

No T02 P&L is computed in this stage.

## Source evidence

Primary source: user-supplied `48位游资-下册`.

### Lower PDF page 118/227 (printed p.87)

The trend-stock profit-taking passage gives unusually concrete exit language:

- a staged advance reaching its objective;
- if there is no intraday new high for three days, leave;
- for trend stocks, a break of the 10-day line is described as a short-wave profit-taking floor.

This supplies literal numeric periods (`3 days`, `10-day line`) but does **not** define the prerequisite population called `trend stocks`, the staged-advance target, the precise timing of a line break, or the executable exit price.

### Lower PDF page 122/227 (printed p.91)

The book's trend-bull operating guidance says, in substance:

- do not rush the buy;
- do not be greedy on the sell;
- operate/roll positions;
- do not delay a stop;
- for trend-style economic bull stocks, prefer low absorption at important locations rather than chasing.

This reinforces that the exit rule belongs inside a broader trend-positioning process. `Important location`, `trend-style economic bull stock`, and the low-absorption setup are not machine-defined there.

### Lower PDF pages 126–127/227 (printed pp.95–96)

A separate passage discusses the 20-day `life line` for trend stocks and mentions usefulness in an approximately 45-degree rising trend. This confirms that the author treats `trend stock` as a contextual chart state, not merely as any stock crossing a moving average. The reviewed passage does not supply a deterministic definition of that state or a machine-safe meaning of `45-degree` trend.

## What is directly grounded

The following pieces are source-grounded enough to preserve literally:

- **three trading days** is the stated persistence window for the no-new-high exit concept;
- **10-day moving average** is the stated line for the short-wave profit-taking floor;
- the rule is conditional on a **trend-stock / trend-bull context**;
- the book treats stop-loss and execution discipline as part of the complete process.

These facts may be used in a future preregistration only if the missing context is supplied independently and fixed before returns.

## What is not machine-ready

The reviewed evidence does not define:

1. a causal, point-in-time predicate for `trend stock`, `trend bull`, `main rise`, or `staged advance`;
2. the objective/target used by `staged advance reaches objective`;
3. whether `no intraday new high for three days` means three consecutive complete sessions after entry, after a local high, or after another anchor;
4. the exact execution timing after the third no-new-high day;
5. whether `break of the 10-day line` is intraday low, close, adjusted close, or another price convention;
6. the executable exit price after the moving-average break;
7. how the 3-day and MA10 exits interact if both occur;
8. whether/rewhen re-entry is allowed after an exit.

## Frozen decision

**`DEFER_TREND_EXIT_PREREGISTRATION`**

The numeric periods are useful source evidence, but the prerequisite state and trigger/execution semantics are not sufficiently defined to preregister a non-arbitrary return test.

T02 therefore authorizes **source extraction only**. It does not authorize:

- applying the 3-day or MA10 exits to the whole CSI800 universe;
- defining `trend stock` from whichever momentum/MA threshold produces the best historical result;
- selecting adjusted/unadjusted price or close/intraday break after viewing P&L;
- return screening;
- X02 changes;
- portfolio combination;
- paper trading;
- live trading.

## Reopening condition

T02 can be reopened only if materially stronger source evidence, or an independently justified pre-return representation, supplies a deterministic trend-state predicate and exact causal trigger/execution semantics. Any operational proxy must be labeled as our proxy and frozen before its returns are inspected.
