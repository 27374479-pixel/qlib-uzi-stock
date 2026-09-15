# V5 M07 frozen result — recovery onset vs leadership emergence

## Outcome

**Status:** `ONTOLOGY_READY_TWO_STAGE_MAPPING_DEFERRED`

The supplied lower volume supports a semantic sequence in which broad market deterioration settles and **recovery begins**, followed by the appearance of **new strong stocks / leadership** as the process develops. M07 therefore freezes:

`RECOVERY_ONSET_CONTEXT -> LEADERSHIP_EMERGENCE_CONTEXT`

This is source ontology only, not a historical classifier.

## Independence from M06

M06 remains frozen as `NOT_SUPPORTED_AS_COMMON_RECOVERY_FACTOR`. M07 does not drop, re-sign, or reassign M06 features based on observed loadings. The two-stage distinction comes from the book's own sequence, not from M06 diagnostics.

## Technical verification

GitHub Actions run `34927104908` completed successfully.

- unit tests: **4 passed**;
- fail-closed ontology verification: passed;
- source review, M06 result and M05 result are SHA-bound in the emitted report.

## Still unresolved

Before any quantitative two-stage validation, a new preregistration must define from source/independent evidence:

- observable assignment to onset vs leadership;
- causal known time;
- whether the stages may coexist;
- transition lag/persistence;
- an independent non-P&L validation target;
- ambiguity handling;
- exact lineage binding.

## Authorization boundary

No historical state labels, W01 return screen, X02 change, portfolio combination, paper trading or live trading are authorized.