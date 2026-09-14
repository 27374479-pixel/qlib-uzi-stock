# V5 W07 source review — W01 market/stock left-side resonance

## Purpose

W07 isolates another statement from the same lower-volume `糊涂118` section before any W01 return screen is opened.

On PDF p.135/227, the follow-up question on the essence of left-side trading says the key is to **wait for resonance between the broad market and the individual stock on the left side**, forming a short-term opportunity; it also emphasizes having a strong grasp of the broad market and waiting for a critical point before intervening.

This is directly relevant to W01: the weak-market stock setup should not be silently treated as a stock-only event. But the passage does not machine-define `left side`, `resonance`, `critical point`, or their causal timing.

## Source-fixed interpretation

The source supports these qualitative constraints:

- market context and stock context both matter;
- a valid left-side opportunity is described as requiring market/stock resonance rather than stock setup alone;
- waiting is part of the method;
- an intervention occurs at some `critical point` rather than at an arbitrary time.

These statements do **not** supply numeric thresholds or a deterministic synchronization rule.

## Frozen readiness requirements

A future resonance preregistration requires, before returns:

1. `market_reference_series` — exact point-in-time broad-market representation;
2. `market_left_side_state` — deterministic causal definition of broad-market left-side state;
3. `stock_left_side_state` — deterministic causal definition of the stock's left-side state;
4. `resonance_operator` — exact logical relation between market and stock states;
5. `synchronization_tolerance` — same-session / lagged-session semantics, if any;
6. `critical_point_definition` — machine-ready meaning of the source's intervention point;
7. `causal_known_time` — earliest timestamp all required states are known;
8. `entry_execution_time` — first executable timestamp after the decision;
9. `mismatch_policy` — explicit no-trade behavior when market and stock states disagree;
10. `independent_validation_or_source_basis` — non-P&L basis for every discretionary mapping;
11. `upstream_lineage_binding` — exact binding to M02 and W02-W06 frozen results.

## Frozen decision

The source clearly supports **market + stock resonance as an architectural requirement**, but it does not define the state variables or synchronization mechanically.

Therefore W07 freezes:

`DEFER_LEFT_SIDE_RESONANCE_PREREGISTRATION`

Allowed action:

`SOURCE_AND_REPRESENTATION_RESEARCH_ONLY`

Not allowed:

- choosing a market index or breadth threshold because W01 returns improve;
- defining `left side` as whichever MA/drawdown rule backtests best;
- trying 0/1/2/3-day resonance windows and keeping the profitable one;
- treating stock-only qualification as equivalent to the source rule;
- opening W01 P&L;
- changing X02, combining sleeves, paper trading or live trading.
