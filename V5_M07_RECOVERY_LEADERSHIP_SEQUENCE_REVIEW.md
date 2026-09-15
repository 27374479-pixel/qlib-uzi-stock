# V5 M07 source review — recovery onset versus leadership emergence

## Purpose

M07 returns to the supplied lower volume after M06's frozen failure. It asks a source question only:

> Does the book itself support treating **market recovery onset** and **emergence of new strong stocks / mature leadership** as distinct stages, rather than forcing every market-tape dimension into one simultaneous recovery factor?

M07 does not inspect strategy returns and does not modify M06.

## Source basis

Lower-volume PDF p.73/227 describes bear-market opportunity as waiting until deterioration becomes quiet and the market **starts to recover**. In the same answer it then says that after a decline wave, **new strong stocks often appear**, and emphasizes that a bear market progresses stage by stage.

This source wording supports a temporal ontology with at least two distinct concepts:

1. `RECOVERY_ONSET_CONTEXT` — broad deterioration is settling and market recovery has begun;
2. `LEADERSHIP_EMERGENCE_CONTEXT` — new strong stocks / leadership begin to appear after that recovery process develops.

The source does **not** state that these stages occur on the same session, does not give a numeric lag, and does not define an exact mapping from M01/M04/M05 variables to either state.

## Independence from M06

M06 was preregistered as a one-factor hypothesis and failed because not all thirteen source-oriented loadings were positive. M07 does not reinterpret or rescue that result. The two-stage distinction is justified only by the book's own sequential wording.

Therefore M07 explicitly forbids:

- dropping M06 features merely because their loadings were negative;
- assigning a feature to a stage based on M06 loadings;
- choosing a lag because it best fits X02/W01 or M06 history;
- treating M06's supportive validator correlations as evidence that either stage is tradable.

## What is source-ready

The source is sufficient to freeze the **semantic ordering**:

`RECOVERY_ONSET_CONTEXT -> LEADERSHIP_EMERGENCE_CONTEXT`

with `UNKNOWN` as the fail-closed system state whenever a mapping is unresolved.

## What remains unresolved

Before any two-stage quantitative validation, a new preregistration must independently define:

- which frozen raw observables belong to onset versus leadership, based on source semantics rather than M06 loadings;
- causal known time for each stage;
- whether stage coexistence is allowed;
- the minimum transition/lag structure to test;
- an independent non-strategy validation target;
- ambiguity handling when broad market and leadership evidence conflict;
- exact lineage binding to M01/M04/M05 and the frozen M06 failure.

## Frozen decision

`ONTOLOGY_READY_TWO_STAGE_MAPPING_DEFERRED`

Allowed action:

`WRITE_SEPARATE_NON_PNL_STAGE_VALIDATION_PREREGISTRATION`

Not allowed:

- market-state labels on historical dates;
- W01 return screening;
- X02 modification;
- portfolio combination;
- paper or live trading.
