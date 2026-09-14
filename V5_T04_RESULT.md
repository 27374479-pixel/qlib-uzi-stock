# V5 T04 frozen result — low-buy position semantics

## Outcome

**Status:** `DEFER_LOW_BUY_POSITION_PREREGISTRATION`

**Allowed action:** `SOURCE_AND_CAUSAL_INTRADAY_REPRESENTATION_ONLY`

T04 preserves a stronger book constraint without opening a return screen: `低吸` means intervention at a **relative intraday low position**, not merely a red/green print and not merely a daily close near MA12.

## Causality guard

The source phrase `全天相对低点` is descriptive. Selecting the eventual full-day low would require future information, so T04 explicitly forbids that interpretation. A future implementation must define a backward-only intraday proxy before any P&L is inspected.

## Relationship to T03

T03's source-fixed MA12 context remains intact. T04 freezes that the daily MA12 condition and the intraday relative-low execution concept are separate layers and may not be collapsed into an optimized close-to-MA threshold.

## Remaining unresolved semantics

The source does not machine-define the backward-only intraday reference window, data frequency/timestamp semantics, relative-low metric/cutoff, causal decision time, executable entry time, auction treatment, limit/suspension policy, MA12 interaction, chase/low-buy conflict policy, or an independent non-P&L validation basis.

## Technical verification

GitHub Actions run `34830433613` completed successfully. The module compiled and emitted the frozen fail-closed report with the expected `DEFER_LOW_BUY_POSITION_PREREGISTRATION` decision.

## Authorizations remain closed

No trend return screen, no T02/T03 combination, no X02 change, no portfolio combination, no paper trading and no live trading are authorized by T04.
