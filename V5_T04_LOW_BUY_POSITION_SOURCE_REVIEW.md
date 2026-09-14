# V5 T04 source review — low-buy position semantics

T04 resolves one source question left by T03: what `低吸` means as a position/style concept. This is source-readiness only and does not inspect strategy returns.

## Source evidence

Lower-volume PDF pp.148–149 distinguishes chasing from low-buy by **relative intraday position**. Chasing is described around an intraday rise / relatively high location, while low-buy is described around a relatively low intraday location. Red or green price color alone does not define the style; relative position does.

This matters for T03: `low-buy around MA12` must not be silently rewritten as `daily close near MA12`.

## Causality guard

The phrase `全天相对低点` is descriptive. A literal implementation that selects the eventual full-day low would use future information and is forbidden. Any executable proxy must be backward-only and preregistered before returns.

## Frozen requirements

A future preregistration must fix, before P&L: the backward-only intraday reference window, bar source/frequency, relative-low metric, qualifying boundary, decision-known time, executable entry time, auction treatment, limit/suspension handling, interaction with the T03 MA12 context, conflict policy between chase and low-buy interpretations, an independent non-P&L validation basis, and exact T03 lineage binding.

## Frozen decision

`DEFER_LOW_BUY_POSITION_PREREGISTRATION`

Allowed action: `SOURCE_AND_CAUSAL_INTRADAY_REPRESENTATION_ONLY`.

No full-day hindsight low, no return-driven intraday threshold/window search, no T02/T03 P&L combination, no X02 change, no portfolio combination, and no paper/live authorization.
