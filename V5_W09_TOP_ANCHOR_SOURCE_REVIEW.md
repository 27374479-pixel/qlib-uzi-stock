# V5 W09 — W01 top-anchor source readiness

## Purpose

W09 addresses another independent W01 prerequisite: the source says the weak-market left-side opportunity occurs **after the leader has topped**, and the 3–7 session / roughly 20%–25% pullback is described relative to that post-top process. W09 asks whether `见顶` is machine-ready before any return screen.

This is source-readiness only. It does not define a top from historical P&L.

## Source evidence

The lower-volume W01 passage gives unusually concrete downstream structure — bear-market context, leader, after topping, first opportunity, roughly 3–7 trading sessions and roughly 20%–25% decline — but it does not specify how a top is recognized in real time.

Nearby material also refers to prior-high areas in descriptive terms, but does not establish whether the anchor is an intraday high, closing high, swing high, or a high that requires later confirmation.

## Causality problem

A retrospective swing high is easy to mark only after lower future prices have occurred. Calling that high `the top` on the same day would leak future information. A causal top representation must distinguish:

- the **price anchor** being tracked;
- the **confirmation event** that makes the anchor knowable as a top;
- the earliest date/time at which the confirmed top may affect a decision.

## Frozen readiness requirements

Before a W01 top-anchor preregistration, all of the following must be fixed without strategy returns:

1. `leader_identity_prerequisite` — which independently validated leader identity is eligible for a top;
2. `price_adjustment_basis` — raw/adjusted treatment and corporate actions;
3. `anchor_price_field` — high, close or another exact field;
4. `candidate_top_rule` — how a candidate high is formed without hindsight;
5. `confirmation_rule` — what later observable confirms the candidate as a top;
6. `confirmation_delay` — exact number/timing of completed observations required;
7. `known_time` — first timestamp when the top may enter a trading decision;
8. `new_high_reset_rule` — how a later new high invalidates/resets the anchor;
9. `drawdown_measurement_basis` — exact top-to-current price fields used for the source's ~20%–25% decline;
10. `three_to_seven_session_clock` — which session starts the source's 3–7 day clock;
11. `first_event_interaction` — binding to the frozen first-event/reset semantics so later pullbacks cannot replace the first one after a failed result;
12. `independent_validation_target_or_source_basis` — non-P&L basis for discretionary choices;
13. `w08_lineage_binding` — exact binding to the frozen W08 leader-evidence result.

## Frozen decision

Current source evidence does not resolve these fields at machine-ready precision. In particular, W08 intentionally validated only descriptive leader evidence and did not authorize a `leader=true` label.

Therefore W09 freezes:

`DEFER_TOP_ANCHOR_PREREGISTRATION`

Allowed action:

`SOURCE_AND_CAUSAL_TOP_REPRESENTATION_ONLY`

Not allowed:

- marking retrospective local maxima as same-day known tops;
- choosing high-vs-close, lookback, confirmation delay or reset rule from W01 returns;
- starting the 3–7 day clock from whichever convention performs best;
- opening W01 P&L;
- changing X02;
- portfolio combination;
- paper or live trading.