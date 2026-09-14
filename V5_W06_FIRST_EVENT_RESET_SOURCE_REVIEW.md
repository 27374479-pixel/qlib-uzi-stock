# V5 W06 source review — W01 `第一次左侧机会` and reset semantics

## Purpose

W06 isolates the word **`第一次`** in the primary W01 passage before any W01 return screen is opened.

The source describes, in bear-market context after a large rebound, an absolute leader topping and then a **first left-side opportunity**, usually around 3–7 trading sessions later after roughly 20%–25% decline. W02/W04 already established that the event shape is source-grounded but the event/top implementation is not machine-ready. W06 now asks a narrower question:

> What exactly makes one post-top observation the *first* qualifying opportunity, and when is the episode reset or consumed?

This is source-readiness only. It does not load strategy returns and does not choose a reset rule from historical profitability.

## Primary source — lower volume PDF p.135/227 (printed p.104)

The source-fixed ordering remains:

`bear context -> large rebound -> absolute leader top -> first post-top left-side opportunity -> approx 3–7 trading sessions / 20%–25% decline`

A later descriptive statement says the stock may rebound toward the prior-high area and stronger cases may make a new high. W05 froze that as post-entry description rather than an exit rule.

## What `第一次` supports directly

The wording supports only the ordinal fact that, within some post-top episode, an **earliest eligible left-side opportunity** is intended to be special. It therefore forbids a research implementation that freely selects the best-looking later qualifying pullback after seeing returns.

## What the source does not machine-define

The reviewed passage does not specify:

- when the post-top episode begins if the top itself is only later confirmed;
- whether `first` means first trading session in the 3–7 window, first touch of ~20% drawdown, first close inside a drawdown band, first intraday low inside it, or a discretionary pattern confirmation;
- whether observations before day 3 can consume/disqualify the first event;
- whether a 20% threshold crossed intraday but not at close counts;
- whether the approximate 20%–25% wording is a band, minimum, target zone, or typical magnitude;
- whether an event is consumed once merely observed, once an order is executable, or only after a fill;
- whether a failed/unfilled first opportunity permits a later one;
- whether a new post-top high *before entry* invalidates the original top and resets the episode;
- whether a later higher high replaces the old top anchor or starts a new leader episode;
- whether multiple same-session observations can exist and, if so, how they are ordered;
- how suspensions/missing stock sessions interact with the market-session count;
- when the event becomes causally known and the earliest permissible entry timestamp.

The source's separate statement that stronger **post-entry** rebounds may make a new high does not answer the **pre-entry reset** question. Those two branches must not be conflated.

## Frozen readiness requirements

A future first-event/reset preregistration requires every item below before returns:

1. `episode_start_rule` — exact causal start of the post-top event episode;
2. `candidate_observation_field` — close/low/other completed field used to determine candidate eligibility;
3. `first_event_predicate` — deterministic definition of a qualifying left-side opportunity;
4. `approx_drawdown_semantics` — non-P&L interpretation of the source's approximate 20%–25% wording;
5. `window_boundary_semantics` — exact day-3/day-7 inclusion and session-zero convention;
6. `pre_window_observation_policy` — whether observations before the source window affect first-event identity;
7. `event_consumption_rule` — when the first opportunity is considered used/consumed;
8. `failed_or_unfilled_event_policy` — whether a later candidate is allowed after execution failure;
9. `pre_entry_new_high_reset_rule` — treatment of a new high before a qualifying/filled event;
10. `replacement_top_rule` — whether/how a newer high becomes a new top anchor;
11. `same_session_ordering_rule` — deterministic ordering if multiple qualifying observations exist;
12. `missing_or_suspended_session_rule` — stock-session versus market-session handling;
13. `event_known_time_and_entry_time` — earliest causal knowledge and first executable timestamp;
14. `independent_validation_or_source_basis` — non-P&L justification for every discretionary item above;
15. `upstream_lineage_binding` — exact binding to W02/W03/W04/W05 and M02 frozen results.

## Frozen decision

The source makes **firstness economically meaningful**, but it does not define the state machine needed to implement firstness causally.

Therefore W06 freezes:

`DEFER_FIRST_EVENT_RESET_PREREGISTRATION`

Allowed action:

`SOURCE_AND_STATE_MACHINE_RESEARCH_ONLY`

Not allowed:

- picking first-touch versus first-close because one has better W01 P&L;
- choosing whether 20%–25% is a band/minimum/target after seeing returns;
- trying reset-on-new-high versus no-reset and keeping the profitable one;
- allowing a later qualifying pullback merely because the literal first one loses money;
- treating failed fills as permission to keep searching unless independently preregistered;
- changing the source-fixed 3–7 session / 20%–25% shape;
- opening W01 P&L;
- changing X02, combining sleeves, paper trading or live trading.
