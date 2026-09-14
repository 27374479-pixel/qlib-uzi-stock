# V5 W09 frozen result — leader-candidate ambiguity

## Outcome

**Status:** `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_LEADER_AMBIGUITY`

GitHub Actions run `34867615677` succeeded. Unit tests: **4 passed**. The full point-in-time audit covered `2021-05-17` through `2026-09-03` (`1,289` dates) with zero frozen invariant failures.

## Descriptive ambiguity

- dates with any sealed-board evidence: **1,159**;
- dates with at least one three-plus-board candidate: **187**;
- dates with multiple simultaneous three-plus-board candidates: **47**;
- dates with a tie at the completed market-maximum board height: **620**;
- dates with at least one conservative first-unsealed-after-3plus proxy: **119**.

Artifact: `v5-w09-leader-ambiguity-results`, id `10357757132`, ZIP SHA-256 `8c2c394f08ff8c67db85010df5902519e6bb7c3617011a0768e923ad2b7a6ddf`.

## Interpretation

The audit establishes that candidate multiplicity is a real structural issue rather than a hypothetical edge case. In particular, completed maximum-board height often does not identify a unique stock, and even at three-plus boards multiple simultaneous candidates occur on a material subset of candidate dates.

This does **not** prove that max-board height is the correct leader lens; W09 deliberately uses it only to expose ambiguity. It also does not choose a tie-breaker or promote any W08 trait intersection into a leader score.

Therefore W01 leader identity remains unresolved. Any later identity rule must be independently preregistered from source/semantic evidence before strategy returns are inspected.

No W01 return screen, top-anchor promotion, X02 change, portfolio combination, paper trading or live trading is authorized.