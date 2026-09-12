# Local event validation — 2026-09-12

## Completed

- Full archive 2021-01-01 through 2026-07-16: 2,023 terminal request dates, 3,875,299 rows; annual and full gates pass.
- Integrated the canonical-aware source audit reader from the existing remote branch, without merging unrelated branch changes.
- Fixed authoritative annual-path detection for Windows separators; two added regression tests pass. The previous 11 tests also pass.
- Source audit: all six canonical annual partitions accepted, no canonical contract violations. CNINFO has 456 unique notices; 441 exact normalized cross-source matches.
- Limitation: CNINFO evidence consists of only two stock files. This is a limited integrity cross-check, not proof of complete market-wide historical coverage. Title normalization is audit-only.

## Causal view and text QA completed

- Built a separate causal event view and frozen market calendar under `data_lake/local_rebuild_20260911/causal`; original archive remains unchanged.
- Inputs: the full local gate and frozen BaoStock equity files. Date-only announcements may be used strictly from the next frozen trading session, never on publication day.
- Manifest `output/local_event_rebuild_20260911/causal_manifest.json` passes: 3,875,299 next-session events, zero same-day/earlier violations; 1,989 price files support the frozen calendar.
- Generated 320 market-blind audit pairs and 240 title examples from a deterministic 6,000-event sample. Avoided retaining token sets for the whole archive; regression confirms eligibility and sampled tokens remain equivalent. Total 14 tests pass.
- Assistant partial review of the 40 highest-band pairs: 35 different-context routine templates, 5 ambiguous. This is not independent human QA. Remaining 280 pairs are unreviewed.
- All 35 confirmed negatives score >= .85, above every preregistered threshold (.30 through .70). Even granting all remaining 285 pairs true-positive status yields precision at most 285/320 = 89.0625%, below the 90% floor. This conditional bound depends on the recorded title-review labels; it is not a full calibration measurement.

## Still locked

- Text-only semantic calibration, frozen clustering configuration, point-in-time replay invariance and the formal H04/H05 unlock gate remain prerequisites.
- No new performance outcome test has been run. Archive completion is not evidence of profitable alpha.
- Formal unlock invocation stopped at missing cluster freeze. The text-only evidence now demonstrates why freezing the current representation would be inappropriate. Improve economic-context eligibility/representation under a new documented text-only version, recalibrate, then replay and unlock. Do not lower the precision floor or force generic filings into theme clusters to obtain backtest returns.

## Evidence

- `output/local_event_rebuild_20260911/gate_full.json`
- `output/local_event_rebuild_20260911/source_audit.json`
- `output/local_event_rebuild_20260911/source_audit_stock_days.csv`
- `output/local_event_rebuild_20260911/causal_manifest.json`
- `output/local_event_rebuild_20260911/text_audit_manifest.json`
- `output/local_event_rebuild_20260911/text_pairs_partial_review.csv`
- `output/local_event_rebuild_20260911/text_review_diagnostic.json`
