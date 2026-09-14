# V5 W02 source review — W01 leader / top / first-pullback semantics

## Purpose

W02 is a **source-readiness gate**, not a W01 backtest.  W01 already has two unusually concrete source numbers: the first post-top left-side opportunity is described as occurring roughly **3–7 trading sessions** after the relevant top and after roughly a **20%–25% decline**.  The same passage also requires bear-market context, an absolute/true leader, and that this be the **first** opportunity after the leader tops.

W02 asks whether the supplied books define the remaining event identity precisely enough to preregister a causal W01 signal **without looking at W01 or X02 returns**.

## Primary source — lower volume PDF p.135/227 (printed p.104)

The passage describes a bear-market setup after a broad rebound.  Its target is a leader stock after topping.  It says the strongest left-side opportunity is the **first one after the leader tops**, usually after roughly **3–7 trading sessions** and roughly **20%–25% decline**.  It separately warns that the stock must be an absolute leader and that it must be the first post-top occurrence.

This source directly fixes:

- context: bear market / weak-market setup is a prerequisite;
- target category: a leader, emphasized as an absolute leader;
- event order: leader tops first, then the first post-top left-side opportunity;
- elapsed-session window: `3–7` trading sessions;
- decline magnitude: approximately `20%–25%`.

It does **not** machine-define:

- how to identify the unique absolute leader from a point-in-time universe;
- what historical window or cross-sectional evidence establishes leader identity;
- what prior upward-wave qualification is required before a top can exist;
- whether the top is the highest close, intraday high, adjusted high, board-cycle high, or another anchor;
- when a top becomes *known* without future information;
- whether the `20%–25%` decline is high-to-close, high-to-low, close-to-close, adjusted/unadjusted, or measured from some other price;
- what resets the event after a failed attempt or a later new high;
- the exact executable entry/exit price and causal decision timestamp.

## Corroborating source — lower volume PDF pp.148–149/227 (printed pp.117–118)

A separate trader explicitly links low-buy/low-absorption methods to bear-market conditions and explains that “low” is relative rather than an absolute price concept.  This corroborates the architectural separation between weak-market low-buy research and other tactics, but does not resolve the missing W01 leader/top mechanics.

## Relationship to existing V5 evidence

- **M01** has validated a causal raw market-tape representation only.
- **M02** has frozen `DEFER_MARKET_CYCLE_CLASSIFIER_PREREGISTRATION`; therefore W01 still lacks a validated bear-state handoff.
- **L01** has a descriptive per-stock board-stage representation, but it was not validated as the unique `absolute leader` identity required by this W01 passage.  W02 must not silently equate an L01 high-board stage with W01 leader identity.
- Existing negative leader experiments must not be used to choose whichever alternative leader definition makes W01 profitable.

## Frozen readiness requirements

A future W01 event preregistration requires every item below to be fixed before returns:

1. `bear_state_handoff` — independently validated weak/bear state, with causal lineage;
2. `leader_identity_basis` — deterministic point-in-time definition of the required absolute leader;
3. `prior_wave_qualification` — rule proving a material preceding upward wave rather than an arbitrary local high;
4. `top_anchor_rule` — exact price anchor and causal confirmation rule for “topped”;
5. `first_pullback_rule` — deterministic meaning of the first post-top event, conditional on a valid top;
6. `drawdown_basis` — exact numerator/denominator and adjusted-price semantics;
7. `drawdown_window` — source-fixed `3–7` trading sessions;
8. `drawdown_magnitude` — source-fixed approximately `20%–25%` decline;
9. `causal_decision_time` — first timestamp at which all inputs are known and an order may be considered;
10. `event_reset_or_duplicate_rule` — treatment of later highs, repeated entries, failed first events and overlapping tops;
11. `independent_validation_or_source_basis` — non-P&L basis for every discretionary semantic mapping;
12. `upstream_lineage_binding` — exact binding to the frozen M01/M02 and source-review artifacts.

## Frozen source-readiness decision

The numeric window and decline magnitude are source-ready.  The economically decisive leader identity, top anchor, prior-wave definition, first-event mechanics and bear-state handoff are not.

Therefore W02 freezes:

`DEFER_W01_EVENT_PREREGISTRATION`

Allowed action:

`SOURCE_AND_REPRESENTATION_RESEARCH_ONLY`

Not allowed:

- running W01 returns;
- trying multiple leader definitions and keeping the most profitable;
- choosing close-high versus intraday-high top anchors from P&L;
- altering the source `3–7` window or `20%–25%` decline to create a pass;
- substituting an L01/B01/B02/B03 leader proxy without a pre-return semantic justification;
- changing X02;
- combining W01 with X02;
- paper trading or live trading.

## Interpretation boundary

The source is unusually strong on **event shape** but still incomplete on **event identity**.  W02 preserves that distinction.  It is legitimate to carry the literal `3–7 sessions` and `20%–25% decline` forward; it is not legitimate to manufacture `absolute leader`, `top`, or `first post-top event` from historical strategy performance.
