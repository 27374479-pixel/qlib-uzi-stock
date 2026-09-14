# V5 W01 source review — bear-market leader pullback / left-side setup

## Purpose

W01 is a **source-readiness review**, not a return test. Its purpose is to decide whether the supplied books define a weak-market / bear-market low-buy setup well enough to preregister a falsifiable experiment without inventing the missing market regime, leader identity, top anchor, or execution rule from historical P&L.

This is directly relevant to the V5 all-weather goal: X02 is a risk-on/momentum sleeve, so a genuinely independent weak-market sleeve would be useful. That usefulness is **not** permission to manufacture a weak-market rule.

## Source evidence

### Primary rule: `48位游资-下册`, 糊涂118 section, PDF p.135/227 (printed p.104)

The source describes a bear-market left-side opportunity with unusually concrete numeric structure:

- context is a **bear market**;
- the stock has already completed a substantial upward wave / rebound and then topped;
- it should be a **leader**;
- the setup is the **first** left-side opportunity after that top;
- the pullback occurs over roughly **3–7 trading days**;
- the decline is roughly **20%–25%**;
- the text frames the essence of left-side trading as waiting for a high-quality opportunity in which the broader market and the individual stock reach a favorable resonance / inflection area.

The literal numeric window `3..7 sessions` and drawdown band `20%..25%` are source-derived and must not be optimized.

### Corroborating architecture: `48位游资-下册`, 乔帮主 section, PDF pp.148–149/227

A separate trader discussion distinguishes chase/limit-up methods from low-buy methods and explicitly links low-buy's comparative usefulness to bear-market conditions. This corroborates the **method-selection-by-regime** architecture, but it does **not** supply a numeric bear-market classifier and is not used to change the primary rule above.

The two trader passages are therefore not fused into one synthetic trading rule. W01 uses the second passage only as independent qualitative support that a weak-market low-buy sleeve is a source-grounded research direction.

## What is directly specified

The following items are source-ready and frozen exactly:

- `pullback_window_sessions_min = 3`
- `pullback_window_sessions_max = 7`
- `drawdown_fraction_min = 0.20`
- `drawdown_fraction_max = 0.25`
- `first_post_top_occurrence = true`
- setup context requires a bear/weak-market state
- setup context requires a leader and a prior material upward wave followed by a top

## What is **not** machine-ready

The reviewed source does not deterministically define:

1. **bear-market state** — no point-in-time index/breadth/MA/drawdown threshold is supplied;
2. **leader identity** — the passage does not specify market-total leader, sector leader, max board height, return rank, or another machine rule;
3. **prior upward-wave qualification** — `一波大反弹/上涨` is not given a numeric return, duration, or structural threshold;
4. **top anchor** — no exact point-in-time definition of the top is supplied;
5. **drawdown measurement basis** — high-to-close, high-to-low, adjusted/nominal, and exact boundary handling are unspecified;
6. **market/stock resonance** — no numeric observable or mapping is supplied;
7. **entry timing and price** — reaching a 20–25% pullback band does not by itself define an executable order time/price;
8. **exit / holding rule** — no deterministic horizon or exit for this exact setup is supplied;
9. **economic control** — the correct matched control is not defined by the source.

These missing items cannot be selected by looking at which historical version makes the strategy profitable.

## Frozen readiness decision

Current status must be:

`DEFER_BEAR_PULLBACK_PREREGISTRATION`

until **all** missing machine definitions above are grounded independently of W01 return outcomes.

The only allowed current action is:

`SOURCE_EXTRACTION_ONLY`

No W01 P&L screen is authorized. In particular, do not use the repository's existing `weak_market`, breadth, index-MA, X02 gate, or a fitted drawdown regime as a convenient substitute for the missing source-defined bear-market state.

## Prohibited rescue / leakage

Before stronger source or independently validated representation evidence exists, do not:

- change 3–7 days to a historically better window;
- change 20–25% to another drawdown band;
- redefine leader from whichever proxy gives the best backtest;
- infer the market regime from W01 returns;
- choose high-to-close vs high-to-low drawdown by performance;
- choose an entry/exit rule from the best historical curve;
- subset years/industries/themes to create a pass;
- combine an undefined W01 sleeve with X02 and call the portfolio all-weather.

A future return experiment must first create a separate preregistration commit after the missing definitions are resolved. W01 itself is governance evidence, not alpha evidence.