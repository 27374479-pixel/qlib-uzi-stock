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
| U-L2 | Upper volume, leader-trait list | The leader discussion lists three-board start, first-wave disagreement with historical-high turnover, accessible board-by-board turnover and >=1bn CNY disagreement turnover among traits; it also says a launch price below 10 CNY provides more room for speculation. | A/B | B01 tested one literal disagreement/participation conjunction and did not qualify. U04 separately preregistered the exact `<10 CNY` launch-price claim as a relative modifier within accessible three-board starts. The one-shot result was **INSUFFICIENT**: development had only 17/17 selected/control executable observations and 2 paired dates; historical-later had 31/52 observations but only 5 paired dates. Do not move the 10-CNY threshold, redefine launch price, or loosen context to create samples. |
| U-L3 | Upper volume, nearby total-leader / followers passage | The extract contains a rough two/three-day total-leader ebb phrase plus nearby language about followers becoming replacement leaders and consensus/recognition. | B/C | U03 source-readiness review **deferred signal preregistration before returns**. The available multi-column OCR interleaves neighboring concepts, so target identity, leader/target relation, consensus observable, ranking, entry, exit and economic control are not safely defined. No U03 return screen is authorized without materially better source evidence. |
| L-S1 | Lower PDF page 68/227 (printed p.37) | A mature short-term system commonly trades on roughly a next-day / 1–2 day holding rhythm; several tactics are listed as examples rather than a universal entry rule. | A for horizon, C for tactic definitions | Justifies 2 trading days as a recurring primary horizon for short-term screens; it does not create alpha by itself. |
| L-S2 | Lower PDF page 119/227 (printed p.88) | In a short/medium-term stock-selection checklist, stocks with a downward 20-day moving-average direction are excluded. The same checklist also excludes disordered charts, no-base structures, unreadable forms, consolidation/wash stages and non-main-rise stages, and says environment/theme/sentiment/safety matter. | A for MA20 direction; C for the broader contextual items | K01 isolated the literal MA20-direction veto and found it not robust. Therefore the isolated rule is not promoted; the broader checklist must not be reverse-engineered from K01 outcomes. |
| L-S3 | Lower PDF page 120/227 (printed p.89) | Profitable short-term trading is described as trend-up / main-rise / leader-style participation within a complete transaction system and disciplined execution. | C | Do not map 'main rise' to arbitrary momentum thresholds. Needs a stronger source definition before coding. |
| L-T1 | Lower PDF page 118/227 (printed p.87) | For trend stocks, the text discusses a staged large advance, leaving if no intraday new high for three days, and using a break of the 10-day line as a short-wave profit-taking floor. | A/B | 'Three days' and '10-day line' are concrete, but the prerequisite definition of a trend stock / staged advance is not machine-ready. Do not test these generically across all stocks until that context is grounded. |
| L-L1 | Lower PDF page 123/227 (printed p.92) | A leader's rough evolution is described as launch -> confirmation -> fermentation -> acceleration -> disagreement -> counter-wrap -> dragon-return. The explanation characterizes early stages as continued growth/recognition, acceleration as broad market awareness, and disagreement as buyers/sellers no longer sharing one view. | B | L01 established structural coherence only. L02 then preregistered one narrow economic interpretation **before returns**: frozen `confirmation` should have positive and superior 2d next-open expectancy versus frozen `disagreement`. L02 was **REJECTED** with sufficient samples: confirmation had negative absolute 2d mean return in both partitions and paired bootstrap lower bounds did not clear zero. No other stage pair may be substituted to rescue L02. |
| L-R1 | Lower PDF pages 68, 71, 72–73, 117–120/227 | The text treats cash/no-trade as legitimate, describes markets as cyclical, distinguishes stronger/poorer market conditions, rejects a large prior decline as a sufficient buy reason, and says timing/environment/theme/sentiment/safety matter. | B/C | R01 froze the fail-closed router. R02 then reviewed classifier readiness **before any classifier P&L** and returned `DEFER_NUMERIC_CLASSIFIER_PREREGISTRATION`: the source does not define a point-in-time market-opportunity observable, deterministic state mapping, numeric threshold basis, or independent noncircular validation label. `UNKNOWN -> CASH_ONLY` remains mandatory. |

## Negative-evidence register

Negative and non-qualifying results are first-class evidence and remain frozen:

- **B01:** literal leader first-disagreement + high-participation conjunction did not qualify.
- **B02:** market-max leader first-yin followed by next-open purchase was rejected with ample samples.
- **B03:** market-max leader, 2/3 non-sealed sessions, first reseal, next-open purchase was insufficient and had negative absolute 2-day expectancy in both historical partitions.
- **K01:** isolated MA20-downward veto was not validated despite hundreds of thousands of observations; development had the wrong relative sign and both periods lacked a positive bootstrap lower bound.
- **L02:** frozen L01 `confirmation` versus `disagreement`, next-open entry and 2d horizon was rejected with sufficient samples. Development confirmation mean net return was -1.7125% and historical-later was -2.5149%; paired relative point estimates were positive but both 95% bootstrap intervals crossed zero. This exact economic interpretation is not promoted and cannot be rescued by choosing another stage pair after seeing the result.
- **U04:** exact source-derived `<10 CNY` launch-price modifier within accessible three-board starts was **INSUFFICIENT**. Development had 17 selected and 17 control executable observations on 17 dates each, with only 2 paired dates; historical-later had 31 selected and 52 control observations, but only 5 paired dates. Descriptive selected 2d mean returns were -1.0332% and -4.8290% in the two partitions. The five-date historical-later relative point estimate was positive but is not promotable. Do not change the threshold, launch-price definition, board count, accessibility condition, horizon, cost, or subsets to rescue it.

These results prohibit 'rescue' through post-result threshold moves. A new experiment needs a new source claim or a separately justified operationalization fixed before seeing its result.

## Representation / source-readiness evidence register

Representation/source-governance outcomes are neither positive alpha evidence nor negative alpha evidence:

- **L01:** the frozen leader-stage proxy is `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_STAGE_AUDIT`. It produced 7,116 labelled rows across 1,085 CSI800 instruments and 1,289 dates, with zero frozen-definition invariant failures. This validated representation coherence, not economic value; L02's later negative economic test does not invalidate L01 as a descriptive representation.
- **U03:** replacement-leader source readiness is `DEFER_SIGNAL_PREREGISTRATION`. The gate passed its technical CI but intentionally left return-screen authorization false because the upper-volume OCR does not safely define the full mechanical rule.
- **R02:** opportunity-classifier source readiness is `DEFER_NUMERIC_CLASSIFIER_PREREGISTRATION`. Five gate tests passed; the defer is intentional. The supplied source supports cash/waiting architecture but not a numeric `OPPORTUNITY_PRESENT` classifier. No classifier P&L screen or X02 gate change is authorized.

## Architecture evidence register

Architecture evidence constrains how future components may interact without claiming a profitable signal:

- **R01:** source review supports a first-class cash/no-trade state and adaptive method selection, but not a numeric market classifier. Router contract V3 therefore fails closed on both sides: a future `OPPORTUNITY_PRESENT` handoff must be preregistered, validated, lineage-verified and bound to contract/validation SHA-256 identifiers; every claimed `RESEARCH_ONLY` or `PAPER_ONLY` sleeve must independently carry a lineage-verified authorization contract and artifact SHA-256. A malformed or self-declared handoff remains inactive, and live trading remains false.
- **R02:** stronger source extraction confirmed that terms such as good/poor market, cycle transition, decline settling and recovery beginning are not numeric market-state rules in the supplied passages. Historical strategy P&L must not be used to reverse-engineer those missing definitions.

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

For representation programs such as L01, structural validation does not inherit economic validity. Economic testing starts a new preregistered experiment. Source-readiness programs such as U03/R02 may stop before preregistration when the source is too ambiguous; that defer result cannot be bypassed by historical threshold search. Architecture programs such as R01 may freeze safe state/authorization behavior but cannot manufacture an `OPPORTUNITY_PRESENT` classifier or a sleeve authorization from prose/self-declaration.

## Next research queue

Priority is based on source clarity, representation quality and pre-result sample coverage, not on observed returns:

1. **Trend-stock prerequisite source extraction (L-T1/L-S3):** the source gives concrete exit language (`three days without a new high`, `10-day line`) but the prerequisite `trend stock / staged advance / main-rise` state is not machine-ready. Continue source extraction only; do not test the exit rules across the whole universe until that prerequisite is grounded.
2. **Opportunity classifier evidence (L-R1):** R02 is frozen deferred. Reopen only if materially stronger source or representation evidence supplies the missing market observable/mapping without strategy-P&L circularity.
3. **Replacement-leader / follower source extraction (U-L3):** U03 is frozen deferred. Reopen only if a cleaner page/image or materially clearer passage resolves target identity, relationship, ranking and timing.
4. **U-L2 remaining traits:** do not mine the same leader-trait list after B01/U04 outcomes. A further economic experiment from this list is allowed only when it tests a distinct literal source claim with a new preregistration fixed before returns and without changing thresholds/context to rescue B01 or U04.

This ledger is research governance, not a trading signal and not an authorization to change X02 or any frozen experiment.
