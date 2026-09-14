# V5 source-grounded research plan

Status: preregistration scaffold only. No result-driven threshold search is authorized by this document.

## Research rule

The V5 all-weather line must start from claims in the two user-supplied 48-trader books, not from generic factor ideas. Every candidate must preserve this chain:

`book claim -> measurable point-in-time proxy -> frozen hypothesis -> historical validation -> execution replay -> only then portfolio combination`

A failed frozen hypothesis is recorded as failed. Thresholds are not moved after seeing its result. A generalized variant requires a separately named experiment and a new preregistration.

## Source-grounded claim registry

### B01: leader emergence with disagreement and real participation

Book source: upper volume, section around the market-leader characteristics. The source explicitly groups together: three-board launch, the first disagreement accompanied by unusually large volume, repeated board-by-board turnover, large disagreement turnover, and leaders that may begin before an index adjustment has fully ended.

Testable interpretation:
- leader status must be measurable from completed data only;
- distinguish `one_word / inaccessible acceleration` from `tradable high-participation leadership`;
- test whether first meaningful disagreement plus sustained participation has better subsequent expectancy than (a) one-word acceleration and (b) late climax chasing;
- market context is tested as an interaction, not used as an ex-post label.

Primary variables already available or derivable from the repository:
- consecutive sealed-board height;
- touch/seal/broken-board state;
- turnover rate and amount acceleration;
- theme breadth and broken-board ratio;
- point-in-time market breadth / money effect;
- next-open executable returns with locked-limit unfilled handling.

### B02: leader first-disagreement / return-to-leader family

Book source: upper volume describes leader methods including first-negative-day / leader-return / second-wave style setups.

Testable interpretation:
- start from a stock that had a previously observable leader state;
- define the first material loss of consensus without using future recovery;
- compare subsequent recovery/continuation expectancy with matched non-leader drawdowns;
- require a separate intraday replay before treating a daily precursor as tradable.

This is a family of hypotheses, not one free-form strategy. The daily precursor and the intraday reclaim trigger must be evaluated separately.

### B03: emotion cycle / market environment

Book source: lower volume explicitly describes recurring market cycles and describes bear/down-trend conditions as materially different trading environments. It also stresses trading with the prevailing trend and waiting when conditions are not suitable.

Testable interpretation:
- market state is a conditioning variable, not a license to optimize hindsight thresholds;
- define market states only from information known at the decision time;
- test whether the same leader/disagreement setup has stable or materially different expectancy across states;
- cash is an allowed sleeve when no source-grounded setup is validated for a state.

### B04: participation / crowd and sentiment propagation

Book source: lower volume emphasizes herd behavior and emotion propagation as major forces, and the upper volume describes leadership through attention, consensus and participation.

Testable interpretation:
- use breadth, amount acceleration, turnover, leader count, broken-board ratio, and theme participation as observable proxies;
- do not use future theme winners or ex-post narrative labels;
- test participation as an interaction with leader state rather than as a standalone generic momentum factor.

### B05: trend and non-participation rules

Book source: lower volume describes trend-following discipline and explicitly lists conditions in which the trader should not participate.

Testable interpretation:
- negative findings can become veto/risk rules even if they are not alpha sleeves;
- evaluate whether vetoes improve drawdown / tail loss without destroying most of the validated alpha;
- a veto is accepted only if it survives development and later historical segments with fixed definitions.

## Immediate experiment order

1. Audit existing H01-H15 and label each hypothesis as `DIRECT_BOOK`, `BOOK_DERIVED`, or `EXPLORATORY`.
2. Promote only DIRECT_BOOK / BOOK_DERIVED hypotheses into the V5 source-grounded queue.
3. First new family: `B01 leader emergence + first disagreement + tradable participation` because the book gives the most concrete observable structure.
4. Second family: `B02 first-disagreement / leader-return` with a strict daily precursor and later minute-level confirmation.
5. Third family: `B03 state conditioning`, using book-derived market-cycle concepts to test stability rather than to hand-tune a router.

## Validation requirements

For each frozen candidate report:
- exact source passage / section reference;
- exact causal variables and timing;
- selected and matched control cohort;
- 2021-2023 and 2024+ results separately;
- executable next-open or minute-level entry, including unfilled cases;
- gross and net results;
- bootstrap / date-cluster uncertainty;
- yearly and rolling-window stability;
- concentration and best-trade sensitivity;
- explicit failure status if the preregistered rule does not survive.

## Boundaries

- D01 low-vol trend remains exploratory because it was not directly derived from the supplied books.
- Existing X02 remains frozen; no post-result retuning is permitted.
- No strategy is called all-weather merely because a historical router improves one interval.
- A final all-weather portfolio requires multiple independently validated sleeves or an explicit cash state, with correlations and joint drawdown tested after the sleeves are frozen.
