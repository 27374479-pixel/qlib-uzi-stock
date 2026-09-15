# V5 M06 source review — bear-market recovery transition semantics

## Purpose

M06 asks whether the supplied books define `BEAR_RECOVERY_CONTEXT` tightly enough to preregister a deterministic state transition over the already frozen M01/M04/M05 representations. This is source-readiness only: no strategy returns are inspected.

## Source evidence

Lower-volume PDF pp.71–74 says markets are cyclical and, in bear-market discussion, describes opportunity as appearing only after a decline becomes quiet/stable and recovery begins. The same passage says that after one wave finishes, new strong stocks may appear. It also warns that a prior decline by itself is not a sufficient buy reason.

Lower-volume PDF pp.100–103 separately says market/main-board sentiment matters and daily review should collect market structure such as advance/decline participation, limit-up and failed-limit activity, consecutive-board structure and the subsequent behavior of prior strong stocks.

M01 made a conservative subset of those raw tape observables causal. M04 added cross-industry dispersion. M05 added one-completed-session changes in those frozen observables.

## What the source constrains

The source supports a directional sequence:

1. deterioration / continued decline;
2. decline pressure settling;
3. recovery beginning;
4. new strong-stock opportunity may then appear.

It also explicitly rejects `large prior decline = opportunity` as a sufficient rule.

## What remains undefined

The source does not machine-define:

- which M01/M04/M05 dimensions are necessary versus optional;
- whether `settling` means lower downside pressure, fewer limit-downs, fewer failed boards, improved breadth, improved prior-winner treatment, or a conjunction;
- numeric boundaries for any dimension;
- how many sessions of improvement are required;
- whether a prior `BEAR_DECLINE_CONTEXT` must first be proven and for how long;
- how conflicting dimensions are resolved;
- whether recovery must broaden across industries;
- exact causal decision time and first tradable session;
- an independent, non-strategy-return validation target for the semantic transition.

## Frozen readiness requirements

A future recovery-transition preregistration must define, independently of X02/W01 returns:

1. `prior_bear_state_requirement`;
2. `settling_observable_set`;
3. `recovery_observable_set`;
4. `necessary_vs_optional_logic`;
5. `boundary_basis`;
6. `persistence_rule`;
7. `transition_reset_rule`;
8. `conflict_and_ambiguity_policy`;
9. `cross_industry_broadening_role`;
10. `decision_known_time`;
11. `first_effective_trading_time`;
12. `independent_validation_target`;
13. `m01_m04_m05_lineage_binding`.

## Frozen decision

Current evidence is not machine-ready for a recovery classifier.

`DEFER_BEAR_RECOVERY_TRANSITION_PREREGISTRATION`

Allowed action: `SOURCE_AND_INDEPENDENT_STATE_VALIDATION_ONLY`.

Not allowed: threshold search on X02/W01 returns, clustering then naming profitable clusters as recovery, W01 P&L, X02 changes, portfolio combination, paper trading or live trading.
