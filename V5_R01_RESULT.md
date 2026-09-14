# V5 R01 frozen result — opportunity / no-opportunity architecture

## Outcome

Source extraction status: **ARCHITECTURE_EVIDENCE_ONLY**  
Numeric regime classifier: **NOT AUTHORIZED / NOT IMPLEMENTED**  
Current effective state: **UNKNOWN -> CASH_ONLY**

R01 reviewed the supplied-book passages about adapting methods to different market conditions, using cash as a legitimate state, waiting when timing is immature or the market is unfavorable, and jointly considering environment, theme/风口, sentiment and safety.

Those passages are strong enough to justify a fail-closed architecture, but they do **not** provide defensible numeric thresholds for breadth, index return, turnover, sentiment, limit-up counts or moving-average regime labels. R01 therefore deliberately stops before constructing a market classifier.

## Frozen router contract V2

The router now recognizes exactly three opportunity states:

- `UNKNOWN`
- `NO_TRADE`
- `OPPORTUNITY_PRESENT`

`UNKNOWN` and `NO_TRADE` both route to `CASH_ONLY`.

A caller cannot activate `OPPORTUNITY_PRESENT` merely by passing a `VALIDATED` status string. The V2 handoff additionally requires:

- non-empty classifier contract ID;
- `status == VALIDATED`;
- `preregistered == true`;
- `lineage_verified == true` from the upstream artifact verifier;
- a well-formed 64-hex classifier-contract SHA-256;
- a well-formed 64-hex validation-artifact SHA-256.

The R01 router explicitly does **not** claim to open or re-hash future external classifier files itself. Its job is to reject an incomplete handoff and make the lineage boundary explicit.

Even with a valid future classifier handoff, the router can only expose sleeves with their own `RESEARCH_ONLY` or `PAPER_ONLY` authorization and evidence ID. An `UNAUTHORIZED` sleeve remains inactive. A failed strategy therefore cannot be rescued simply by placing it behind a regime filter.

## Verification

The V2 CI contract suite passed **13 tests**. The emitted current stub remained:

- requested state: `UNKNOWN`;
- effective state: `UNKNOWN`;
- action: `CASH_ONLY`;
- active sleeves: none;
- classifier handoff: missing/invalid;
- live trading authorized: false;
- portfolio optimization authorized: false.

## Interpretation boundary

R01 is governance and architecture evidence, not alpha evidence. It does not say when an opportunity is present. It only establishes the safe behavior while that knowledge is absent.

A future numeric opportunity classifier requires its own source evidence, frozen observables, preregistration, historical validation and immutable validation artifact. Until then, the system must fail closed to cash rather than infer that an unclassified market is tradable.
