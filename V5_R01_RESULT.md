# V5 R01 frozen result — opportunity / no-opportunity architecture

## Outcome

Source extraction status: **ARCHITECTURE_EVIDENCE_ONLY**  
Numeric regime classifier: **NOT AUTHORIZED / NOT IMPLEMENTED**  
Current effective state: **UNKNOWN -> CASH_ONLY**

R01 reviewed the supplied-book passages about adapting methods to different market conditions, using cash as a legitimate state, waiting when timing is immature or the market is unfavorable, and jointly considering environment, theme/风口, sentiment and safety.

Those passages are strong enough to justify a fail-closed architecture, but they do **not** provide defensible numeric thresholds for breadth, index return, turnover, sentiment, limit-up counts or moving-average regime labels. R01 therefore deliberately stops before constructing a market classifier.

## Frozen router contract V3

The router recognizes exactly three opportunity states:

- `UNKNOWN`
- `NO_TRADE`
- `OPPORTUNITY_PRESENT`

`UNKNOWN` and `NO_TRADE` both route to `CASH_ONLY`.

A caller cannot activate `OPPORTUNITY_PRESENT` merely by passing a `VALIDATED` status string. The classifier handoff additionally requires a contract ID, preregistration flag, upstream lineage verification, and well-formed SHA-256 identifiers for both the classifier contract and validation artifact.

V3 also closes the analogous sleeve-authorization hole. A caller cannot make a strategy eligible simply by writing `authorization=PAPER_ONLY` or `RESEARCH_ONLY`. Each claimed non-`UNAUTHORIZED` sleeve must carry:

- a non-empty evidence ID;
- a non-empty authorization contract ID;
- `authorization_lineage_verified == true` from the upstream artifact verifier;
- a well-formed 64-hex authorization-artifact SHA-256.

A malformed claimed authorization is reported and stays inactive. An explicitly `UNAUTHORIZED` sleeve is also inactive. Thus both sides of the router — **market opportunity** and **strategy eligibility** — fail closed.

The R01 router deliberately checks the handoff envelope rather than pretending to verify future external files that it has not opened. A later integration must perform the actual immutable-file hashing upstream and pass the verified lineage into this contract.

## Verification

The V3 CI contract suite passed **16 tests**. It covers missing/malformed classifier lineage, missing/malformed sleeve authorization lineage, duplicate sleeves, unauthorized sleeves, valid research/paper sleeves and the default fail-closed stub.

The emitted current stub remained:

- requested state: `UNKNOWN`;
- effective state: `UNKNOWN`;
- action: `CASH_ONLY`;
- active sleeves: none;
- classifier handoff: missing/invalid;
- invalid claimed sleeve authorizations: none, because the stub claims none;
- live trading authorized: false;
- portfolio optimization authorized: false.

## Interpretation boundary

R01 is governance and architecture evidence, not alpha evidence. It does not say when an opportunity is present. It only establishes the safe behavior while that knowledge is absent.

A future numeric opportunity classifier requires its own source evidence, frozen observables, preregistration, historical validation and immutable validation artifact. A future sleeve likewise requires its own immutable authorization artifact. Until those exist and are independently verified, the system must fail closed to cash rather than infer that an unclassified market or self-declared strategy is tradable.
