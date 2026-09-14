# V5 M06 frozen result — source-aligned recovery polarity

## Outcome

**Status:** `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_RECOVERY_POLARITY`

M06 validates only the per-dimension direction map over the frozen M05 one-session changes. It does not assign any date to `BEAR_RECOVERY_CONTEXT` and does not create a score.

## Historical structural audit

GitHub Actions run: `34852980695`

- unit suite: **4 passed**;
- historical period: `2021-05-17` through `2026-09-03`;
- represented dates: `1,289`;
- duplicate dates: `0`;
- date-lineage mismatches: `0`;
- oriented-delta mismatches: `0`;
- polarity-sign mismatches: `0`;
- missingness-preservation failures: `0`;
- fabricated first-row deltas: `0`.

Artifact:

- `v5-m06-recovery-polarity-results`
- artifact id: `10352690176`
- ZIP SHA-256: `055d08af6437d21736db79472638700ffde3eb1759b6b990fb46287838438bdf`

## Interpretation boundary

A positive M06 polarity means only that one frozen dimension moved in the source-aligned repair/broadening direction. M06 does not say how many dimensions must improve, whether improvement must persist, or what starting level is required.

Therefore no majority vote, all-of-N rule, weighted score, persistence window, quantile, cluster or threshold may be promoted to a market-cycle classifier from this result.

## Authorizations remain closed

No market-state label, no recovery score, no W01 return screen, no X02 change, no portfolio combination, no paper trading and no live trading are authorized by M06.