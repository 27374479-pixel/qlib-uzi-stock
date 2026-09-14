# V5 market-state evidence addendum — M03 to M05

This addendum preserves the market-state research chain created after the central evidence ledger's M02 entry. It is governance evidence, not a trading signal.

## M03 — source-grounded market-cycle ontology

Frozen result: `ONTOLOGY_READY_MAPPING_DEFERRED`.

The supplied lower volume supports a minimal semantic vocabulary without consulting strategy returns:

- `BEAR_DECLINE_CONTEXT`;
- `BEAR_RECOVERY_CONTEXT`;
- `BULL_BROADENING_CONTEXT`;
- system-only fail-closed fallback `UNKNOWN`.

The source qualitatively supports `BEAR_DECLINE_CONTEXT -> BEAR_RECOVERY_CONTEXT` and longer bull/bear cycling. It does not supply date-level mapping boundaries, lookback/persistence, transition confirmation, causal order time or an independent validation target.

CI run `34838882651`: 4 tests passed.

## M04 — leadership-dispersion representation

Frozen result: `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_DISPERSION`.

To preserve the source idea that a stronger broad market is not merely one isolated hotspot, M04 measures point-in-time cross-industry participation/concentration from historical as-of industry snapshots. It records positive/sealed/first-board/multi-board industry breadth plus top-industry share and HHI concentration for leadership activity.

Historical structural audit: 1,289 dates (`2021-05-17` to `2026-09-03`), zero frozen invariant failures. CI run `34839228861`: 4 tests passed.

No historical quantile is a bull/bear threshold.

## M05 — recovery-dynamics representation

Frozen result: `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_RECOVERY_DYNAMICS`.

The lower volume describes bear-market opportunity as appearing only after deterioration settles and recovery starts, and separately names advance/decline balance, limit activity, failed-limit activity, board structure and prior-strong-stock behavior as review inputs.

M05 therefore freezes normalized M01/M04 levels and their one-completed-session first differences only. The one-session difference is the smallest causal change observable and avoids selecting a fitted lookback. Missing prior-winner samples remain missing rather than being filled with zero.

Historical structural audit: 1,289 dates (`2021-05-17` to `2026-09-03`), zero frozen invariant failures. CI run `34841799492`: 5 tests passed.

Coverage:

- prior-seal level 1,157 dates; one-session delta 1,047 dates;
- prior-multi-board level 484 dates; one-session delta 300 dates.

## Current authorization boundary

M03-M05 improve semantic and raw representation layers only. They do not authorize:

- historical date labels for bear/recovery/bull;
- a weighted recovery score;
- minimum-count or sign-combination rules;
- thresholds or persistence chosen from X02/W01 returns;
- W01 P&L;
- X02 changes;
- portfolio combination;
- paper or live deployment.

## Next research priority

The remaining bottleneck is no longer raw observability. It is **independent state-mapping validation**: a future experiment must justify how M01/M04/M05 observations map to the M03 ontology without using the strategy returns that the state is intended to gate. If no such independent target or stronger source rule is found, the correct system behavior remains `UNKNOWN -> CASH_ONLY`.