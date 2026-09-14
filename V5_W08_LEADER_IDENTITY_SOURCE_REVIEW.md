# V5 W08 source review — W01 leader identity

## Purpose

W01 uses a lower-volume passage about a bear-market leader stock's first post-top left-side opportunity. Before any W01 P&L can be opened, W08 asks whether `leader stock` is machine-ready from the supplied books without importing a profitable proxy after the fact.

## Source distinction

Lower-volume PDF p.135/227 says the weak-market setup concerns a `leader stock` after a prior large rebound/up-wave and after the leader tops. The passage gives the later 3–7 session / roughly 20%–25% pullback structure, but does not qualify the word `leader` as market-total, sector, theme or return-rank leader.

The upper volume separately discusses `market total leader`, says total-leader tactics include first-yin / dragon-return / second-wave, and lists traits such as a persistent major theme, continuing news fermentation, a three-board start, first disagreement with historically high turnover, board-by-board accessibility, >=1bn CNY disagreement turnover, starting before the end of an index adjustment and launch price below 10 CNY.

Those upper-volume traits are useful source evidence, but W08 does **not** assume that lower-volume `leader stock` and upper-volume `market total leader` are identical concepts.

## Important negative evidence

B02 previously used `point-in-time market maximum consecutive-board height` as an explicitly declared operational proxy for market-total leadership. Its economic first-yin hypothesis was rejected. That rejection does not prove the proxy is semantically wrong, but it also does not authorize silently reusing the proxy for W01.

Likewise, B01/U04 failures do not permit dropping or retuning individual upper-volume leader traits until a profitable leader definition is found.

## Required fields before W01 leader-identity preregistration

1. `leader_scope` — market-total, sector/theme, or another explicitly sourced scope;
2. `identity_observables` — exact point-in-time fields that establish leadership;
3. `trait_conjunction_or_precedence` — which source traits are mandatory, optional or tie-breakers;
4. `theme_or_sector_relation` — whether theme/sector identity is required and how it is known point-in-time;
5. `leadership_start_time` — first completed timestamp at which the stock may be called a leader;
6. `leadership_persistence` — whether identity persists after a non-board day and for how long;
7. `tie_policy` — treatment when multiple names satisfy the same leadership evidence;
8. `handoff_policy` — when leadership transfers to a replacement/follower;
9. `accessibility_policy` — how one-word/locked boards affect identity versus tradability;
10. `independent_validation_target` — a non-W01-return basis for falsifying the operational identity;
11. `causal_data_lineage` — exact point-in-time data sources and corporate-action policy;
12. `w01_lineage_binding` — binding to the frozen W01 source-readiness contract.

## Frozen decision

Current source evidence is not machine-ready for W01 leader identity.

`DEFER_W01_LEADER_IDENTITY_PREREGISTRATION`

Allowed action: `SOURCE_AND_LEADER_REPRESENTATION_RESEARCH_ONLY`.

Not allowed: choosing market-max-board, sector rank, momentum rank, turnover, amount, price, theme breadth or any composite because it improves W01 returns; opening W01 P&L; changing X02; portfolio combination; paper/live trading.