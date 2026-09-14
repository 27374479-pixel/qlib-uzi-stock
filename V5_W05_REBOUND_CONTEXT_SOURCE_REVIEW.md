# V5 W05 source review — W01 `大反弹以后` context and post-entry reference

## Purpose

W05 isolates two phrases in the same primary W01 passage that have not yet been made machine-ready:

1. the setup occurs in a bear market **after a large rebound** (`大反弹以后`);
2. after the left-side entry, the stock is described as often rebounding quickly toward the **prior high area** (`前期高点附近`), with stronger cases even making a new high.

This review exists to prevent two silent substitutions:

- treating `大反弹` as an arbitrary stock-specific prior wave when the passage itself does not machine-define its scope;
- converting `前期高点附近` into an exact exit rule chosen from W01 returns.

W05 is source-readiness only. It does not load strategy returns or market data.

## Primary source — lower volume PDF p.135/227 (printed p.104)

The passage's sequence is:

`bear-market context -> large rebound -> leader tops -> first post-top left-side opportunity -> approximately 3–7 trading sessions / 20%–25% decline -> possible quick rebound toward the prior high area`

It also separately requires an absolute leader and the first occurrence after topping.

### What the wording supports directly

- `bear market` is a prerequisite context;
- some `large rebound` occurs before the leader-top setup;
- the leader-top event precedes the source-fixed 3–7-session / ~20%–25% decline;
- after entry, a rebound toward a prior-high area is described as a common outcome, not a guaranteed rule;
- stronger rebounds can exceed the prior high, so `prior high` is not automatically a hard profit cap.

### What it does not machine-define

The phrase `大反弹` does not specify:

- whether the rebound belongs to a market index, broad market, theme, or the individual leader;
- which market/index/universe represents it;
- its start/end anchors;
- minimum magnitude or duration;
- whether the rebound must have ended before the leader tops;
- the causal timestamp at which `large rebound completed` is known.

The phrase `前期高点附近` does not specify:

- which previous high is referenced;
- high versus close price;
- raw versus adjusted price;
- what numerical distance counts as `附近`;
- whether reaching it is a take-profit trigger, merely a descriptive expectation, or a region in which to reassess;
- what happens when price makes a new high before an exit.

## Important semantic correction

Earlier W01 readiness notes used a generic `prior_wave_qualification` placeholder. W05 freezes a stricter interpretation boundary: the source clearly says the setup follows a **large rebound**, but it does **not** authorize silently translating that phrase into a stock-specific prior-wave rule.

Until stronger evidence exists, the research contract must keep these concepts distinct:

- `market/rebound context` — unresolved scope;
- `absolute leader identity` — independently unresolved by W03;
- `leader top` — independently unresolved by W04;
- `source-fixed post-top pullback shape` — approximate 3–7 sessions and 20%–25%;
- `prior-high-area rebound` — descriptive post-entry expectation, not an executable exit rule.

## Frozen readiness requirements

A future W01 context/target preregistration requires every item below before returns:

1. `rebound_scope` — market/index/theme/stock scope of `大反弹`;
2. `rebound_reference_series` — exact causal series/universe used to represent that scope;
3. `rebound_start_anchor` — backward-only start definition;
4. `rebound_end_anchor` — deterministic end definition;
5. `rebound_magnitude_rule` — non-P&L basis for what counts as `大`;
6. `rebound_duration_rule` — if duration matters, its source/independent basis;
7. `rebound_known_time` — earliest timestamp the rebound state is known;
8. `rebound_to_leader_top_relation` — deterministic ordering and overlap rule;
9. `prior_high_reference` — exact historical high region referenced after entry;
10. `prior_high_near_definition` — mechanical meaning of `附近` if it is ever used;
11. `post_entry_target_role` — descriptive expectation versus actual exit/reassessment rule;
12. `new_high_after_entry_rule` — treatment of the source-described stronger/new-high case;
13. `independent_validation_or_source_basis` — non-P&L justification for all discretionary mappings;
14. `upstream_lineage_binding` — exact binding to M02/W02/W03/W04 and the evidence ledger.

## Frozen decision

The passage provides a useful **sequence of concepts**, but neither `大反弹` nor `前期高点附近` is machine-ready enough to become an execution rule.

Therefore W05 freezes:

`DEFER_REBOUND_CONTEXT_PREREGISTRATION`

Allowed action:

`SOURCE_AND_REPRESENTATION_RESEARCH_ONLY`

Not allowed:

- trying index/stock rebound windows and retaining the one with best W01 P&L;
- converting arbitrary market-tape quantiles into `大反弹` after seeing returns;
- treating an individual-stock prior wave as source-mandated without additional evidence;
- optimizing the numerical meaning of `前期高点附近`;
- using prior-high touch as an exit rule merely because it backtests well;
- opening W01 P&L;
- changing X02, combining sleeves, paper trading or live trading.
