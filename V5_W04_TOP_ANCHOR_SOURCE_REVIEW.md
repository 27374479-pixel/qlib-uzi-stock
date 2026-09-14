# V5 W04 source review — W01 `top` anchor and 20%–25% drawdown basis

## Purpose

W02 established that the lower-volume W01 passage directly fixes a powerful event skeleton: bear-market context, an absolute leader, the **first** left-side opportunity after that leader tops, roughly **3–7 trading sessions**, and roughly **20%–25% decline**. W03 then showed that the strongest supplied leader-trait material still does not define a unique causal `absolute leader` classifier.

W04 isolates a different missing layer: even if a valid leader were handed in, what exact observation constitutes `见顶`, from what price is the 20%–25% decline measured, and when is that top known without future information?

W04 is a **source-readiness gate only**. It does not load W01 returns and does not choose an anchor from P&L.

## Primary W01 source — lower volume PDF p.135/227

The primary passage says the strongest left-side opportunity comes after the leader has topped, normally around 3–7 trading sessions later after roughly a 20%–25% decline, and stresses that this must be the first occurrence.

The passage fixes:

- event ordering: top first, then decline, then first left-side opportunity;
- elapsed window: approximately `3–7` trading sessions;
- decline magnitude: approximately `20%–25%`.

It does **not** say whether `top` means:

- the session intraday high;
- the session close;
- the highest adjusted or unadjusted price in a preceding wave;
- a high that is only confirmed after one or more later sessions fail to make a new high;
- a board-cycle high, close-based swing high, or another technical anchor.

It likewise does not say whether the subsequent decline is measured top-high-to-current-close, top-high-to-current-low, close-to-close, or with another price field.

## Nearby but non-transferable source — lower volume trend-stock material

A separate lower-volume trader gives rules for **trend stocks**, including selling when there is no new intraday high for three days and treating a break of the 10-day line as a short-wave profit-taking floor. That material is a different tactic with a different prerequisite state (`trend stock / trend bull`).

It cannot silently supply W01's leader-top definition because:

- W01 says the leader **has topped** before its 3–7-session / 20%–25% pullback opportunity;
- the trend rule is an exit heuristic, not a definition of the top price itself;
- its prerequisite trend-state semantics are themselves deferred in T02;
- importing the three-day rule would add a new confirmation lag and change W01 event timing without source permission.

Therefore W04 records this passage as evidence that future-looking top confirmation is a real causal issue, but **not** as authorization to define W01 top by “three days without a new high.”

## Causal ambiguity

A raw local maximum is trivial to label retrospectively but not necessarily known at the time. For example, calling session T the top because no later session in T+1…T+N exceeds it uses future data unless the decision is delayed until those confirming sessions have completed.

That distinction matters because the W01 clock itself is only 3–7 sessions. A top-confirmation rule that waits several sessions can consume much of the source-fixed window and materially change the event. Such a choice must be fixed from source/independent representation logic, not chosen after seeing returns.

## Frozen readiness requirements

A future top-anchor preregistration requires all of the following before W01 returns:

1. `top_price_field` — exact price field used as the top anchor;
2. `price_adjustment_basis` — raw/forward-adjusted/back-adjusted semantics and corporate-action treatment;
3. `preceding_wave_anchor_scope` — exact backward-only region within which the top is eligible;
4. `top_confirmation_rule` — deterministic rule that makes the top known causally;
5. `top_known_time` — earliest timestamp when the top identity and price may be used;
6. `session_zero_and_elapsed_counting` — whether top day is day 0 and exactly how 3–7 trading sessions are counted;
7. `drawdown_observation_field` — close/low/other field used for the post-top observation;
8. `drawdown_formula` — exact numerator/denominator and sign convention;
9. `drawdown_threshold_interpretation` — how the source's approximate 20%–25% wording becomes a frozen mechanical condition without tuning;
10. `first_qualifying_event_rule` — deterministic definition of the first qualifying observation;
11. `new_high_reset_rule` — treatment of a later high before a qualifying pullback;
12. `missing_or_suspended_session_rule` — how non-trading stock days interact with the market trading-session window;
13. `decision_and_entry_time` — when the signal may first be acted on after the qualifying observation;
14. `independent_validation_or_source_basis` — non-P&L justification for every discretionary mapping;
15. `upstream_lineage_binding` — bind W02/W03/M02 and the evidence ledger.

## Frozen decision

The source fixes **how far** and **roughly how long after a top**, but not the causal price/time semantics needed to know what that top is or how to measure the decline.

Therefore W04 freezes:

`DEFER_TOP_ANCHOR_PREREGISTRATION`

Allowed action:

`SOURCE_AND_REPRESENTATION_RESEARCH_ONLY`

Not allowed:

- comparing intraday-high, close-high, rolling-high or swing-high anchors by W01 returns;
- importing the unrelated three-day trend-stock exit rule as W01 top confirmation;
- deciding high-to-close versus high-to-low from whichever backtest performs better;
- changing the source-fixed 3–7-session / ~20%–25% event shape;
- opening W01 P&L;
- changing X02, combining sleeves, paper trading or live trading.
