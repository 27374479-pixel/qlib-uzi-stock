# V5 T02 result — trend-stock exit-rule source readiness

## Frozen outcome

**Status: `DEFER_TREND_EXIT_PREREGISTRATION`.**

T02 deliberately stops before any return screen. The book gives two useful literal exit parameters — **3 sessions** for the no-intraday-new-high concept and a **10-day moving-average line** for the short-wave profit-taking floor — but it does not provide enough machine-ready context to test those rules without inventing important pieces.

## What passed source readiness

The following are preserved as literal source evidence:

- `no_new_high_window_sessions = 3`;
- `moving_average_period_sessions = 10`;
- both rules are conditional on a trend-stock / trend-bull context rather than the entire universe.

These values are not fitted and must not be changed later to improve results.

## What remains undefined

The gate remains closed because the reviewed passages do not deterministically define:

- the prerequisite `trend stock / trend bull / main rise / staged advance` state;
- the anchor from which the three-session count begins;
- the executable timing/price after the third no-new-high session;
- whether a `10-day-line break` means intraday low, close, or another price test;
- the executable timing/price after the MA10 break;
- adjusted versus nominal price basis;
- precedence/interaction between the two exits;
- re-entry policy.

Defining any of those from whichever historical version yields the best P&L would be precisely the kind of post-hoc rule invention V5 is designed to avoid.

## Authorization boundary

Current effective action is **`SOURCE_EXTRACTION_ONLY`**.

T02 does **not** authorize:

- exit-rule preregistration yet;
- a historical return/P&L screen;
- applying the exits generically to CSI800;
- X02 changes;
- portfolio combination;
- paper trading;
- live trading.

A future reopening requires materially stronger source evidence or an independently justified, pre-return trend-state representation plus exact causal execution semantics.

## Technical record

GitHub Actions run `34812002754` completed successfully.

- unit tests: **5 passed**;
- fail-closed decision assertion: passed;
- source-review SHA-256: `5c46558ee41719106e85ab95bd6ea6fd7604ea679bacfe886cf3d797c2c1521b`;
- artifact: `v5-t02-trend-exit-source-readiness`;
- artifact id: `10334504856`;
- uploaded ZIP SHA-256: `27993afb600377f5b109cd0de5a767ec9a185e0b94eac46602147a106ee3dc0f`.

This is a governance/source-readiness outcome, not positive or negative alpha evidence.
