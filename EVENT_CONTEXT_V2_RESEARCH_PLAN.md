# Economic-context recovery candidate v2

Status: text-only development, not calibrated, not authorized by the formal H04/H05 gate.

## Why change

The original similarity representation groups generic filing templates. Its highest-band audit supplied 35 negative examples out of 40 reviewed pairs. Raising/lowering a cosine threshold does not add missing economic meaning.

## Implemented boundary

`event_context_candidate_v2.py` routes titles into routine, unresolved, and body-review-required classes. Action categories are retrieval aids only, never theme IDs. Routine notices are not deleted: a title can conceal an important transaction, so unresolved and routine classes need false-negative QA too. Action matches override the routine wrapper and require review.

The streaming scanner reads only event ID, instrument, title, publication date and source URL. It samples 100 body-review candidates per year by deterministic event-ID hash. It never reads returns, current concept membership or winning-stock labels. Existing raw files, v1 calibration and formal preregistration are unchanged.

## Next evidence needed

1. Review retained and rejected samples separately. The old 320-pair set is development evidence; improvements on it do not count as fresh validation.
2. Fetch original source documents for a small deterministic pilot. Preserve source URL, original publication date, retrieval timestamp, document hash and revision information. Today's retrieval time is not historical availability. Do not include later corrections in earlier history.
3. Extract document-supported product/project/counterparty, action, direction (positive/negative/cancellation), and quoted supporting passage. Missing information means abstention. Business action alone is insufficient for a cross-company context.
4. Form candidate shared contexts only from grounded common economic entities/products/events and causally available records. Recalibrate on a new blind text sample with the original precision floor; check recall/coverage and hard negatives, including unrelated contracts and opposing event directions.
5. Freeze an explicitly versioned representation and replay algorithm. Run past-prefix and row-order invariance checks. Only after the revised evidence chain passes may the experiment runner consume outcomes.

## Important limitations

This is a routing prototype, not a validated theme model or profitability result. A small queue establishes feasibility, not market-wide completeness. Rule vocabulary itself requires text-only QA and a fresh holdout before promotion. No relaxation of the 90% precision requirement is proposed.
