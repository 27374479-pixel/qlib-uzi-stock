# V5 M03 source review — market-cycle ontology

## Purpose

M03 narrows one missing item from M02: the **state vocabulary**. It does not map M01 tape values into states and does not inspect strategy returns.

## Stronger source evidence

Lower-volume pp.71–73 explicitly treats the market as a recurring bull/bear cycle. The bear-market discussion distinguishes an ongoing weak/down market from the later point where the decline settles and recovery starts; the opportunity discussion says the latter is materially different from simply having fallen a lot.

Lower-volume p.130 separately discusses characteristics of a `true bull market`: capital is described as sufficiently abundant for broader flowering / multiple opportunities rather than requiring one isolated hotspot to carry the market.

These passages support a small semantic ontology without requiring any return optimization.

## Frozen source-grounded vocabulary

The following semantic states are frozen for research vocabulary only:

1. `BEAR_DECLINE_CONTEXT` — a weak/bear context in which the market is still in a declining/deteriorating phase.
2. `BEAR_RECOVERY_CONTEXT` — a bear-context recovery phase after decline has settled enough for recovery to begin.
3. `BULL_BROADENING_CONTEXT` — a bull context characterized qualitatively by broader opportunity / multiple active areas rather than a single isolated hotspot.
4. `UNKNOWN` — system fallback when the evidence does not support one of the three source states. `UNKNOWN` is a fail-closed architecture state, not a claim that the book names an extra market regime.

## Transition semantics

The source supports only a **partial qualitative ordering**:

- `BEAR_DECLINE_CONTEXT -> BEAR_RECOVERY_CONTEXT` is a source-supported conceptual progression;
- bull/bear conditions are cyclical over longer horizons.

It does **not** provide a deterministic transition function, a minimum persistence duration, or numeric tape boundaries. M03 therefore does not authorize state assignment.

## What remains unresolved

A future classifier still needs, independently of X02/W01 P&L:

- deterministic M01-observable -> state mapping;
- numeric or rule-based boundary basis;
- lookback / persistence;
- exact transition confirmation;
- causal decision timestamp;
- conflict/ambiguity policy beyond fail-closed `UNKNOWN`;
- independent noncircular validation target;
- binding to the frozen M01/M02/M03 lineage.

## Frozen decision

`ONTOLOGY_READY_MAPPING_DEFERRED`

Allowed action: `SOURCE_AND_INDEPENDENT_MAPPING_RESEARCH_ONLY`.

No threshold fitting from X02/W01 returns, no W01 P&L, no X02 change, no portfolio combination, no paper/live authorization.
