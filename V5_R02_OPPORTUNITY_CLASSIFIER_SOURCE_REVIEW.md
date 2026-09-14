# V5 R02 — opportunity / no-opportunity classifier source review

## Decision before any classifier backtest

**DEFER_NUMERIC_CLASSIFIER_PREREGISTRATION**

R02 returns to the user-supplied `48位游资-下册` and asks a narrower question than R01:

> Does the supplied source define enough **point-in-time, machine-defensible market observables** to preregister a numeric `OPPORTUNITY_PRESENT` versus `NO_TRADE` classifier without inventing thresholds?

The answer from the reviewed passages is **no**.  The book gives strong architecture and behavior guidance, but it does not define a numerical market-state classifier.

This review is frozen before any R02 market-state return screen.  A deferred result must not be bypassed by trying breadth, index-return, limit-up-count, turnover, moving-average or sentiment thresholds against historical P&L.

## Source evidence reviewed

### Lower PDF page 68/227 (printed p.37)

The mature short-term discussion explicitly includes multiple tactics and **cash**.  It also distinguishes market quality: when the market is good, the text describes fuller participation / leader chasing; when the market is poor, it advises not chasing highs, preferring low-entry tactics or cash.

Safe implication: **method choice is conditional on market quality and cash is a legitimate action**.

Unsafe implication: the page does not define how a machine decides that the market is "good" or "poor".

### Lower PDF page 71/227 (printed p.40)

The text describes the market as cyclical: one round ends and a new round begins, with adjustment / elimination / updating along the way.

Safe implication: a static always-on method is not the only architecture contemplated by the source.

Unsafe implication: the page does not provide numeric boundaries for cycle start/end.

### Lower PDF pages 72–73/227 (printed pp.41–42)

The bear-market discussion warns that a large prior decline is not by itself a reason to buy, emphasizes patience, and describes opportunities as appearing after a downward wave settles and recovery begins.  It also says cash makes those new opportunities easier to capture.

Safe implication: **"already fell a lot" is not a sufficient opportunity signal**; waiting through hostile phases is source-consistent.

Unsafe implication: "settled", "recovery begins" and "new strong stock" are not machine-defined on these pages.

### Lower PDF page 117/227 (printed p.86)

The text says that when timing is immature or the market is unfavorable, risk should be faced rationally and one should wait.  It specifically explains that being flat allows objective market analysis without a position interfering with judgment.

Safe implication: `NO_TRADE -> CASH_ONLY` is source-grounded.

Unsafe implication: the page does not specify a numeric trigger that moves the market from `UNKNOWN` to `NO_TRADE` or `OPPORTUNITY_PRESENT`.

### Lower PDF page 119/227 (printed p.88)

The short/medium-term stock-selection checklist gives six "do not participate" items: downward 20-day average direction; disordered K-line structure; no effective base; unreadable/unclear structure; consolidation/wash stage; and non-main-rise stage.  It also says environment, theme/风口, sentiment and capital properties must be considered jointly.

Only the **20-day-average direction** item is directly machine-readable without inventing a proxy.  It is an **individual-stock veto**, not a market opportunity classifier.  K01 already tested that isolated literal veto and did not validate it economically; R02 therefore does not repurpose it as a market-state threshold.

The other checklist terms remain contextual unless a stronger source passage defines them mechanically.

## What the source supports now

R02 marks these architecture claims as source-ready:

- cash/no-trade is a first-class action;
- market quality/cycle should influence method choice;
- being flat is appropriate when timing is immature or the market is unfavorable;
- a large decline alone is not a buy signal;
- "opportunity" is described as state-dependent rather than always present.

These statements support the existing R01 fail-closed router.  They do **not** activate `OPPORTUNITY_PRESENT`.

## What is still missing for a numeric classifier

Before any numeric classifier may be preregistered, the source or a separately justified representation study must establish all of the following without looking at strategy P&L:

1. a point-in-time observable definition of market opportunity / non-opportunity;
2. a deterministic mapping from those observables to states;
3. any numerical thresholds, if thresholds are required;
4. how ambiguous/conflicting evidence maps to `UNKNOWN`;
5. a validation target that does not circularly define "opportunity" as "days on which X02 made money";
6. immutable lineage for the classifier contract and its validation artifact.

Current supplied-book passages do not satisfy items 1–3.

## Prohibited translations

R02 specifically forbids silently turning the prose into rules such as:

- CSI800 breadth above 50% = opportunity;
- index above MA20 = opportunity;
- limit-up count above N = opportunity;
- broken-board ratio below X = opportunity;
- money effect above zero = opportunity;
- after a Y% index decline, recovery of Z% = opportunity;
- MA20 stock veto aggregated into a market regime.

Those may be reasonable research ideas in another context, but the reviewed book passages do not supply those thresholds.  Searching them against historical returns would be parameter mining, not source translation.

## R02 authorization boundary

R02 authorizes only a **source-readiness gate** and documentation update.

It does not authorize:

- numeric classifier implementation;
- classifier return/P&L screening;
- X02 gating changes;
- sleeve activation;
- portfolio optimization;
- paper trading;
- live trading.

Until materially stronger source evidence or an independently preregistered representation program exists, the R01 production/research handoff remains:

`UNKNOWN -> CASH_ONLY`.
