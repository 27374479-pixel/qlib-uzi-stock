# V5 W06 frozen result — first-event and reset semantics

## Outcome

**Status:** `DEFER_FIRST_EVENT_RESET_PREREGISTRATION`

**Allowed action:** `SOURCE_AND_STATE_MACHINE_RESEARCH_ONLY`

W06 stops before any W01 return screen. The source explicitly privileges the **first** post-top left-side opportunity and preserves the approximate `3–7 trading sessions / 20%–25% decline` shape, but it does not define the causal state machine required to know which observation is first, when an event is consumed, or when an episode resets.

## Source-fixed facts preserved

- ordinal requirement: `first_post_top_left_side_opportunity`;
- approximate elapsed window: `3–7` trading sessions;
- approximate decline magnitude: `20%–25%`;
- later candidates may not replace the first based on better historical P&L;
- the source's post-entry new-high description is not a pre-entry reset rule.

## Missing machine semantics

The source does not currently fix:

- episode start after a causally known top;
- candidate observation field (close/low/other);
- deterministic first-event predicate;
- band/minimum/target meaning of approximate 20%–25%;
- exact day-3/day-7 and session-zero semantics;
- treatment of observations before the source window;
- event consumption on observation/order/executability/fill;
- failed or unfilled first-event handling;
- pre-entry new-high reset and replacement-top rules;
- same-session ordering;
- suspension/missing-session treatment;
- event-known time and first executable entry time;
- independent non-P&L validation basis for these choices.

## Technical verification

Workflow run: `34827975706`

- unit tests: **7 passed**;
- fail-closed verification: passed;
- source review SHA-256: `57cba0dc1aae36ed205cb126974eb730987038e9c9231657a49acec5498887eb`;
- W05 result SHA-256: `1a4cf40cc11905f60feb3b938e763fdd52520787e8cfeebe928a7fd45fa53f5f`;
- artifact: `v5-w06-first-event-reset-source-readiness`;
- artifact id: `10339929704`;
- ZIP SHA-256: `2d81f9351a62f03e7c4e15975eb313ca42c23971df4ff7cfbe501d192f846b64`.

## Authorizations remain closed

- first-event/reset preregistration: false under current evidence;
- W01 event preregistration: false;
- W01 return screen: false;
- X02 change: false;
- portfolio combination: false;
- paper trading: false;
- live trading: false.

A future readiness pass would authorize only a separate preregistration of the state machine. It would not by itself authorize W01 P&L because bear-state, absolute-leader, top-anchor and rebound-context gates remain deferred.
