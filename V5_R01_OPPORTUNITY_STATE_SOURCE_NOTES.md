# V5 R01 — opportunity / no-opportunity source extraction

## Why this exists

The target architecture is not a single always-on stock formula. The supplied books repeatedly describe short-term trading as conditional on whether the current market offers a suitable opportunity, with **cash / no-trade as a legitimate state**.

R01 records that source evidence before any numerical regime classifier is written. The purpose is specifically to prevent us from inventing a breadth, index, turnover or sentiment threshold and then retroactively claiming that the book said it.

## Source evidence

### R01-E1 — different market conditions call for different tactics, including cash

Source: `48位游资-下册`, PDF page 68/227 (printed p.37), short-term-system Q&A.

Faithful paraphrase: the trader describes a mature short-term mode as mainly very short holding periods, but says **different market conditions use different methods**. The listed toolbox includes several active tactics and also **空仓 / cash**.

Classification: **B/C**. The architectural statement is clear; the conditions selecting each tactic are not machine-defined on this page.

Implication: an all-weather system must permit a cash state. It does **not** justify any numerical market threshold.

### R01-E2 — markets are cyclical and the trader must adapt

Source: `48位游资-下册`, PDF page 71/227 (printed p.40), market-cycle Q&A.

Faithful paraphrase: market conditions are described as cyclical rather than permanently fixed, and the trader is told to adjust with the changing rhythm instead of treating one method as timeless.

Classification: **C**.

Implication: do not assume one sleeve is universally active. No specific bull/bear classifier is supplied here.

### R01-E3 — when timing is immature or the market is unfavorable, face risk rather than force a trade

Source: `48位游资-下册`, PDF page 117/227 (printed p.86), section on viewing the market objectively and calmly.

Faithful paraphrase: when timing is not mature or the market is unfavorable to the trader, the text emphasizes rationally facing risk; when opportunity arrives, act. It also explicitly presents **空仓** as enabling more objective market observation and stresses that the market does not lack opportunities.

Classification: **B/C**. `cash when conditions are unsuitable` is source-grounded; `unsuitable` remains discretionary.

Implication: `NO_TRADE` should be a first-class router outcome, not an error or missing signal.

### R01-E4 — environment, theme/air-flow, sentiment and safety must be considered together

Source: `48位游资-下册`, PDF page 119/227 (printed p.88), short/medium-term stock-selection section.

Faithful paraphrase: after listing several stock-level exclusions, the text says decisions must also combine **environment, theme/风口, sentiment and safety**, and that different situations use different methods.

Classification: **C** for the contextual variables; several neighboring stock-level exclusions are more concrete but K01 already showed that extracting one literal item in isolation (MA20 direction) is not enough.

Implication: a future opportunity classifier should be multi-dimensional or explicitly acknowledge missing dimensions. It must not be reduced to one convenient market indicator merely because that is easy to code.

### R01-E5 — complete system and execution discipline matter more than a single trick

Source: `48位游资-下册`, PDF page 120/227 (printed p.89).

Faithful paraphrase: profitable short-term trading is framed as having a complete transaction system, correct execution and participation in suitable upward/main-rise/leader contexts rather than possessing one isolated technical trick.

Classification: **C** for the market-state wording; **architecture evidence** for system-level discipline.

Implication: keep strategy evidence, router evidence and execution evidence separate. A regime filter cannot rescue a failed sleeve after the fact.

## What the source does NOT yet give us

Across these passages we have not found a defensible machine-ready definition for:

- how much breadth is `good` or `bad`;
- an index-return cutoff for `favorable` versus `unfavorable`;
- a turnover threshold for opportunity;
- a sentiment score threshold;
- how many limit-ups / broken boards define a regime;
- whether a particular moving average defines bull/bear;
- a numeric weighting among environment, theme, sentiment and safety.

Therefore R01 **does not authorize a numeric regime classifier** yet.

## Frozen architecture conclusions

The following conclusions are sufficiently source-grounded to encode as architecture without inventing alpha:

1. `NO_TRADE / CASH` is a valid first-class decision state.
2. `UNKNOWN` must remain distinct from `OPPORTUNITY_PRESENT`; missing evidence must never be auto-promoted into a trade state.
3. Different strategy sleeves may be appropriate in different conditions; this does not mean a sleeve can be activated before it has independent evidence.
4. A router may route only among independently authorized research/paper sleeves. It cannot improve a failed sleeve by hiding it inside a regime.
5. No live-trading authorization follows from source extraction or router structure.

## R01 decision

**DO_NOT_BUILD_NUMERIC_REGIME_CLASSIFIER_YET.**

The next engineering step may safely freeze the router **state schema and fail-closed behavior** (`UNKNOWN -> CASH`, `NO_TRADE -> CASH`) because those are governance/architecture properties, not fitted market thresholds. Any transition into an `OPPORTUNITY_PRESENT` state remains unimplemented until a separately sourced and preregistered classifier exists.
