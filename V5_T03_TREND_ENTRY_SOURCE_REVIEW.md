# V5 T03 source review — trend-stock entry and risk literals

## Purpose

T03 revisits the trend-stock line only because the supplied lower-volume book contains a **new, directly numeric passage** that was not part of T02's exit-only gate.

On lower-volume PDF p.135/227 (printed p.104), the trend-stock answer states three concrete ideas:

- a **12-session moving-average line** can be used for low-buy in trend stocks;
- a **break of the 20-session moving-average line** warrants caution;
- an **acute selloff around 20%** can be a good buy area.

These are source literals, not fitted values. T03 asks whether they are sufficiently machine-ready to preregister an entry/risk rule **without looking at P&L**.

## Relation to T02

T02 already froze separate trend-stock exit literals: three sessions without a new intraday high and the 10-session line as a short-wave profit-taking floor. T03 does not rescue or replace T02. It adds a different source passage concerning possible entry/risk locations.

Both T02 and T03 share the same unresolved prerequisite: the book does not machine-define `trend stock / trend bull / main rise` well enough to apply the rules to the whole universe.

## Source-fixed literals

T03 preserves exactly:

- `low_buy_ma_period_sessions = 12`;
- `caution_ma_period_sessions = 20`;
- `acute_selloff_fraction_approx = 0.20`.

No MA11/MA13, 18/22-day line, 15%/25% selloff, or percentile replacement is permitted inside T03.

## What the source does not machine-define

The passage does not specify:

- a deterministic prerequisite `trend_stock` state;
- whether MA12 `low-buy` means intraday touch, low below line, close near line, reclaim, or another pattern;
- what numerical distance from MA12 counts as `near` / low-buy area;
- whether the MA12 observation is known intraday or only at close;
- whether `break MA20` means intraday low below, close below, consecutive closes below, or another event;
- whether `caution` means no new entry, reduce, exit, tighten risk, or simply reassess;
- the anchor/window behind `急杀20%附近`;
- whether the 20% move is high-to-low, close-to-close, swing-high-to-low, or another basis;
- the time horizon over which the acute selloff must occur;
- how the MA12, MA20, and acute-selloff conditions interact when they conflict;
- raw versus adjusted price treatment and corporate-action semantics;
- exact decision time and first executable entry time;
- position sizing, stop, holding horizon, exit, and re-entry;
- an independent non-P&L basis for all discretionary choices above.

## Frozen readiness requirements

A future trend-entry preregistration requires every item below before returns:

1. `trend_stock_predicate`;
2. `price_adjustment_basis`;
3. `ma_calculation_basis`;
4. `ma12_low_buy_observation_rule`;
5. `ma12_proximity_or_cross_semantics`;
6. `ma12_known_time_and_entry_time`;
7. `ma20_break_observation_rule`;
8. `ma20_caution_action_semantics`;
9. `acute_selloff_anchor`;
10. `acute_selloff_measurement_formula`;
11. `acute_selloff_window`;
12. `acute_selloff_known_time_and_entry_time`;
13. `condition_interaction_precedence`;
14. `position_and_exit_semantics`;
15. `independent_validation_or_source_basis`;
16. `t02_lineage_binding`.

## Frozen decision

The numeric source values are unusually useful, but the surrounding trading state and causal execution semantics remain too ambiguous for a return screen.

Therefore T03 freezes:

`DEFER_TREND_ENTRY_PREREGISTRATION`

Allowed action:

`SOURCE_AND_TREND_STATE_REPRESENTATION_ONLY`

Not allowed:

- applying MA12/MA20/20% rules to all CSI800 stocks;
- defining a trend stock from whichever momentum/MA combination produces better returns;
- choosing touch/close/reclaim semantics after seeing P&L;
- changing 12, 20 or ~20% to rescue results;
- combining T03 with T02 into a complete trading strategy before both prerequisite/causal semantics are independently ready;
- opening a trend P&L screen;
- changing X02, portfolio combination, paper trading or live trading.
