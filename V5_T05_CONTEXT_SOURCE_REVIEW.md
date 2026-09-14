# V5 T05 source review — trend-state prerequisite context

## Purpose

T05 revisits lower-volume PDF pp.119–127 to narrow the prerequisite state behind T03/T04. This remains source-readiness only and does not inspect returns.

## Source constraints preserved

The source gives a set of selection/context constraints for short-term participation:

- stocks with a downward 20-session moving-average direction are excluded;
- disordered K-line structure is excluded;
- names without a prior base are excluded;
- unreadable forms are excluded;
- wash/consolidation stages are excluded;
- non-main-rise stages are excluded;
- a separate summary says to do only upward trend, only main-rise, and smooth/leader-like names;
- environment, theme, sentiment, safety and capital character must be considered together rather than replacing context with one technical line;
- the 20-session line is described as particularly useful in an orderly rising trend; nearby wording uses a visual `45-degree` idea, which is not scale-invariant and therefore must not be turned into a numeric chart angle without an independent definition.

## What this does not define

The source does not machine-define `trend up`, `main rise`, `orderly/smooth`, `base`, `wash/consolidation`, `readable form`, or the context variables. It also does not give a deterministic conjunction/precedence rule across these concepts.

The direct MA20-down exclusion has already been isolated historically and was not robust as a standalone alpha rule. T05 therefore treats it only as source evidence about the prerequisite context; it must not be re-promoted by itself or retuned from returns.

## Frozen readiness requirements

Before a trend-state representation can be preregistered, the following must be fixed without strategy P&L: exact price-adjustment basis; MA20 direction observable; trend-up predicate; main-rise predicate; orderly/smooth structure representation; base definition; wash/consolidation exclusion; treatment of unreadable/ambiguous structures; environment/theme/sentiment/safety interfaces; capital-character representation if used; state conjunction/precedence; causal known time; exact handoff to T03/T04; and an independent non-P&L validation target.

## Frozen decision

`DEFER_TREND_STATE_PREREGISTRATION`

Allowed action: `SOURCE_AND_STATE_REPRESENTATION_ONLY`.

No return-driven trend classifier search, no revival of the isolated MA20 rule as alpha, no T02/T03/T04 P&L combination, no X02 change, no portfolio combination, and no paper/live authorization.
