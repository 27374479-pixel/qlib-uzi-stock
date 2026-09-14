# V5 W08 frozen result — source-grounded leader evidence

## Outcome

**Status:** `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_LEADER_EVIDENCE`

W08 validates only a causal descriptive evidence layer for the mechanically representable subset of the supplied upper-volume market-total-leader traits. It does not identify the market total leader.

## Historical structural audit

GitHub Actions run: `34854366292`

- unit tests: **6 passed**;
- period: `2021-05-17` through `2026-09-03`;
- evidence rows: `7,106`;
- instruments represented: `900`;
- sealed-board rows: `6,914`;
- three-plus-board rows: `330`;
- fully observed streak rows: `6,913`;
- known all-accessible-proxy rows: `6,487`;
- conservative first-unsealed-after-3plus proxy rows: `192`;
- amount >= CNY 1bn rows: `4,362`;
- launch-price < CNY 10 rows: `2,300`.

All frozen structural invariants passed with zero failures: duplicate instrument/date, three-plus mapping, accessibility proxy, incomplete-streak launch/access verdicts, launch-price flag and amount flag.

Artifact:

- `v5-w08-leader-evidence-results`
- artifact id: `10351973276`
- ZIP SHA-256: `ac790235993be46ab0b0b3b5999f692e4b1fd22a70371f56326a9c851ae118e9`

## Interpretation boundary

The source directly supports traits such as three-board start, board-by-board accessibility, >= CNY 1bn disagreement amount and < CNY 10 launch price, but W08 does not claim that the representable subset is sufficient to identify a total leader.

The following source traits remain unresolved rather than fabricated: sustained large-theme logic, continued news fermentation, exact history scope for historical-high disagreement amount, end-of-index-adjustment timing, exact turnover semantics, and total-leader identity among multiple candidates.

U04's prior insufficient `<10 CNY` economic result is not revived by this descriptive representation.

## Authorizations remain closed

No leader score, rank or label; no top anchor; no W01 return screen; no X02 change; no portfolio combination; no paper trading and no live trading are authorized by W08.