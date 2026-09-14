# V5 M02 source review — market-cycle state mapping over M01

## Purpose

M02 is a **source-readiness gate**, not a regime backtest and not an alpha test. M01 has already established that the book-grounded market-tape vector can be represented causally and coherently. M02 asks the narrower next question:

> Do the supplied books define a deterministic, point-in-time mapping from that raw tape to market-cycle states well enough to preregister a classifier without looking at X02/W01 returns?

If not, the correct result is to defer. The existence of a valid raw feature layer is not permission to invent thresholds.

## Source evidence

### Lower volume, PDF pp.71–73/227

The text explicitly says markets move in cycles rather than remaining permanently tradable. It describes bear-market decline/recovery as an evolving process and says investors should wait patiently for opportunities instead of assuming that a large prior decline is itself a buy signal. The bear-market discussion uses qualitative stages such as repeated decline and recovery and notes that a trend may emerge after an initial wave.

This provides:

- a source-grounded reason to model market state as **time-varying**;
- a source-grounded reason to distinguish deterioration from recovery;
- a source-grounded warning against a one-variable `large decline = opportunity` rule.

It does **not** provide an exact CSI800/index/breadth threshold, a fixed lookback, or deterministic state-transition rule.

### Lower volume, PDF pp.100–103/227

The review/risk discussion says market or main-board sentiment is important and describes daily review as collecting market data. The review page explicitly names the kinds of tape observations a trader should inspect, including:

- daily advancing/declining participation;
- limit-up / failed-limit-up activity;
- consecutive-board counts;
- performance of prior-day limit-up / consecutive-board stocks;
- broader theme / sentiment context.

M01 operationalized only the directly observable daily-tape subset, without assigning a regime label.

The source does **not** say, for example, `broken_ratio > X => retreat`, `breadth < Y => bear`, or `prior-board mean return > Z => recovery`.

### Upper volume, leader context

The upper-volume leader discussion says strong leaders may start before the end of an index adjustment. This reinforces the interaction between market context and leader behavior, but again supplies no deterministic market-state mapping.

## Frozen readiness requirements

A future M02 classifier preregistration would require all of the following to be defined **independently of X02/W01 strategy returns**:

1. `state_vocabulary` — the exact finite set of market states and their economic meaning;
2. `observable_to_state_mapping` — a deterministic mapping from M01 completed-close fields to those states;
3. `threshold_or_boundary_basis` — why every numeric boundary exists, without optimizing strategy P&L;
4. `lookback_and_persistence_rule` — how many completed sessions define state and how state persists/changes;
5. `transition_rule` — deterministic rules for deterioration/recovery transitions;
6. `causal_decision_time` — when a state is known and when it may first affect an order;
7. `independent_validation_target` — a noncircular target or source standard by which the state representation can be falsified without using the gated strategy's own returns;
8. `ambiguity_policy` — what happens when evidence conflicts or no state is defensible;
9. `lineage_binding` — exact M01 artifact/version binding so a later classifier cannot silently change raw inputs.

## Current source-readiness decision

The reviewed source supports the **architecture** and the **raw observations**, but not items 1–8 at machine-ready precision. Therefore the frozen decision is:

`DEFER_MARKET_CYCLE_CLASSIFIER_PREREGISTRATION`

Allowed action:

`SOURCE_AND_INDEPENDENT_TARGET_RESEARCH_ONLY`

Not allowed:

- fitting or hand-tuning a bull/bear threshold on X02 returns;
- fitting or hand-tuning a weak-market threshold on W01 returns;
- clustering M01 and naming the clusters from whichever one makes strategies profitable;
- taking M01 quantiles and converting them into state thresholds after seeing their historical distribution;
- changing the existing `weak_market` implementation and calling it book-validated;
- opening W01 P&L;
- changing X02;
- portfolio combination;
- paper or live trading.

## Interpretation boundary

M02 intentionally separates three layers:

1. **M01 raw tape representation:** structurally validated;
2. **market-cycle semantic mapping:** not yet machine-ready;
3. **strategy routing:** remains fail-closed until layer 2 is independently validated.

Until stronger source evidence or a separately preregistered independent validation target exists, the R01 router remains `UNKNOWN -> CASH_ONLY` for any sleeve that depends on this missing market-state mapping.
