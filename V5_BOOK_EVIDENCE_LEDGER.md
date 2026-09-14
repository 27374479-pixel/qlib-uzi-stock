# V5 source-grounded book evidence ledger

Purpose: prevent V5 from turning memorable trading phrases into invented algorithms. Every future research hypothesis must point to a source claim here (or add a new sourced entry first), state how much interpretation is required, preregister the mechanical translation before results, and preserve failures without threshold rescue.

## Evidence classes

- **A — directly quantifiable:** the source gives a concrete observable rule or number that can be translated with little discretion.
- **B — named structure, operational proxy required:** the source names a pattern/stage but does not give a machine-ready definition. Research is allowed only if the proxy is declared as our operationalization rather than presented as a verbatim rule.
- **C — contextual/discretionary:** the source idea is meaningful but too ambiguous to code safely without first finding stronger source detail. Do not turn C claims into arbitrary thresholds.

## Ledger

| ID | Source location | Source-grounded claim (paraphrased) | Class | Current treatment |
|---|---|---|---|---|
| U-L1 | Upper volume, market-total-leader section | The market total leader can be approached with named leader tactics such as first-yin, dragon-return and second-wave. | B | B02 literal first-yin daily proxy was rejected; B03 conservative second-wave proxy was insufficient/poor. Do not infer new timing rules from their diagnostics. |
| U-L2 | Upper volume, leader-trait list | The leader discussion lists three-board start, first-wave disagreement with historical-high turnover, accessible board-by-board turnover and >=1bn CNY disagreement turnover among traits. | A/B | B01 tested a literal conjunction and did not qualify. The failure does not license changing 3 boards / 1bn / 20-day high after seeing results. |
| U-L3 | Upper volume, nearby total-leader / followers passage | After a total leader ebbs for roughly two or three days, followers/replacement leaders can emerge; recognition/consensus matters. | B | The two-to-three-day phrase was used only to preregister B03's interruption window and L01's explicitly labelled dragon-return proxy. Replacement-leader research still needs a new source-grounded experiment, not B03 retuning. |
| L-S1 | Lower PDF page 68/227 (printed p.37) | A mature short-term system commonly trades on roughly a next-day / 1–2 day holding rhythm; several tactics are listed as examples rather than a universal entry rule. | A for horizon, C for tactic definitions | Justifies 2 trading days as a recurring primary horizon for short-term screens; it does not create alpha by itself. |
| L-S2 | Lower PDF page 119/227 (printed p.88) | In a short/medium-term stock-selection checklist, stocks with a downward 20-day moving-average direction are excluded. The same checklist also excludes disordered charts, no-base structures, unreadable forms, consolidation/wash stages and non-main-rise stages, and says environment/theme/sentiment/safety matter. | A for MA20 direction; C for the broader contextual items | K01 isolated the literal MA20-direction veto and found it not robust. Therefore the isolated rule is not promoted; the broader checklist must not be reverse-engineered from K01 outcomes. |
| L-S3 | Lower PDF page 120/227 (printed p.89) | Profitable short-term trading is described as trend-up / main-rise / leader-style participation within a complete transaction system and disciplined execution. | C | Do not map 'main rise' to arbitrary momentum thresholds. Needs a stronger source definition before coding. |
| L-T1 | Lower PDF page 118/227 (printed p.87) | For trend stocks, the text discusses a staged large advance, leaving if no intraday new high for three days, and using a break of the 10-day line as a short-wave profit-taking floor. | A/B | 'Three days' and '10-day line' are concrete, but the prerequisite definition of a trend stock / staged advance is not machine-ready. Do not test these generically across all stocks until that context is grounded. |
| L-L1 | Lower PDF page 123/227 (printed p.92) | A leader's rough evolution is described as launch -> confirmation -> fermentation -> acceleration -> disagreement -> counter-wrap -> dragon-return. | B | L01 froze a transparent daily stage proxy and passed a structural-only audit: 7,116 labelled rows across 2021-05-17..2026-09-03, zero label invariant failures, and near-perfect/immediate precursor consistency. This validates only representation coherence, not returns or a trading rule. Any economic test still needs a new preregistration. |
| L-R1 | Lower PDF pages 68, 71, 117–120/227 | The text treats cash/no-trade as a legitimate short-term state, describes markets as cyclical, says not every moment is a suitable opportunity, and requires method choice to consider environment, theme/风口, sentiment and safety. | B/C | R01 extracted the architecture evidence and froze a fail-closed router contract: `UNKNOWN -> CASH_ONLY`, `NO_TRADE -> CASH_ONLY`. The source still does not justify a numeric opportunity classifier. `OPPORTUNITY_PRESENT` remains unavailable without a separately preregistered, validated, artifact-bound classifier handoff. |

## Negative-evidence register

Negative results are first-class evidence and remain frozen:

- **B01:** literal leader first-disagreement + high-participation conjunction did not qualify.
- **B02:** market-max leader first-yin followed by next-open purchase was rejected with ample samples.
- **B03:** market-max leader, 2/3 non-sealed sessions, first reseal, next-open purchase was insufficient and had negative absolute 2-day expectancy in both historical partitions.
- **K01:** isolated MA20-downward veto was not validated despite hundreds of thousands of observations; development had the wrong relative sign and both periods lacked a positive bootstrap lower bound.

These results prohibit 'rescue' through post-result threshold moves. A new experiment needs a new source claim or a separately justified operationalization fixed before seeing its result.

## Representation evidence register

Representation-only results are neither positive alpha evidence nor negative alpha evidence:

- **L01:** the frozen leader-stage proxy is `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_STAGE_AUDIT`. It produced 7,116 labelled rows across 1,085 CSI800 instruments and 1,289 dates, with zero frozen-definition invariant failures. This permits descriptive stage work only; return testing remains locked behind a separate preregistration.

## Architecture evidence register

Architecture evidence constrains how future components may interact without claiming a profitable signal:

- **R01:** source review supports a first-class cash/no-trade state and adaptive method selection, but not a numeric market classifier. Router contract V3 therefore fails closed on both sides: a future `OPPORTUNITY_PRESENT` handoff must be preregistered, validated, lineage-verified and bound to contract/validation SHA-256 identifiers; every claimed `RESEARCH_ONLY` or `PAPER_ONLY` sleeve must independently carry a lineage-verified authorization contract and artifact SHA-256. A malformed or self-declared handoff remains inactive, and live trading remains false.

## Promotion ladder

A source idea must move through the following order:

1. **Source evidence:** page/section and faithful paraphrase recorded here.
2. **Operationalization note:** distinguish source wording from our machine proxy; list every discretionary choice.
3. **Preregistration:** freeze universe, point-in-time fields, entry/exit, costs, horizon, controls, sample gates and statistical gate.
4. **One-shot daily screen:** development + historical-later partitions; no threshold search.
5. **Execution replay:** only after a preregistered daily pass and only when intraday execution is material.
6. **Cross-regime / stability checks:** descriptive unless separately preregistered.
7. **Combination research:** only after individual sleeves have independent evidence. Do not improve a failed sleeve by hiding it inside a portfolio.
8. **Forward paper trial:** only after technical lineage/execution gates; no live authorization follows automatically.

For representation programs such as L01, steps 3–4 are replaced by a frozen proxy specification followed by structural validation. Economic testing starts a new preregistered experiment rather than inheriting a pass from representation work. Architecture programs such as R01 may freeze safe state/authorization behavior but cannot manufacture an `OPPORTUNITY_PRESENT` classifier or a sleeve authorization from prose/self-declaration.

## Next research queue

Priority is based on source clarity, not on which historical diagnostic looked best:

1. **Replacement-leader / follower source extraction (U-L3):** the upper-volume OCR is multi-column and ambiguous. First separate the claims about total-leader ebb, followers/补涨 and competing leaders. Do not code a replacement-leader signal until the source relationship is unambiguous enough to preregister.
2. **Opportunity classifier evidence (L-R1):** continue searching both books for machine-defensible observables. Until then, R01 stays `UNKNOWN -> CASH_ONLY`; do not invent breadth/index/sentiment thresholds.
3. **Leader-stage economic preregistration (L-L1):** L01 representation is coherent, but late states are sparse (counter-wrap 23 rows, dragon-return 27). Before any return is read, decide whether there is enough source justification and coverage for one narrow stage comparison; otherwise defer rather than weaken definitions.
4. **Trend-stock exit rules (L-T1):** defer until a book-grounded, machine-ready definition of the prerequisite trend/main-rise state is found.

This ledger is research governance, not a trading signal and not an authorization to change X02 or any frozen experiment.
