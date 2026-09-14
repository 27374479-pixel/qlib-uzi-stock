# V5 W03 source review — can the books define W01's `absolute leader`?

## Purpose

W02 confirmed that the W01 passage is unusually concrete about the **shape** of the bear-market pullback (`3–7` trading sessions and approximately `20%–25%` decline) but remains blocked on event identity, especially the requirement that the stock be the **absolute leader**.

W03 reviews the strongest leader-identification material in the supplied upper volume **without consulting W01/X02 returns**. It asks only whether the source is precise enough to freeze a unique, causal, point-in-time `absolute leader` definition.

## W01 requirement — lower volume PDF p.135/227

The W01 passage does not merely say “a strong stock.” It explicitly emphasizes that the target must be an absolute/true leader and that the left-side opportunity must be the first one after that leader tops. W03 therefore cannot weaken the requirement to “any high-board stock,” “any sector leader,” or “whichever stock ranks highest under a profitable historical proxy.”

## Strongest available leader source — upper volume, `market total leader` section

The supplied upper-volume text contains a section headed as characteristics of the **market total leader** and describes the leader as the most-followed focus whose recognition is formed collectively. Nearby text says total-leader tactics include first-yin, dragon-return and second-wave approaches.

The characteristic list contains these source items:

1. persistent / major-theme support with strong theme logic;
2. continuing news/message fermentation;
3. three-consecutive-board launch;
4. first-wave disagreement accompanied by historically high volume accumulation;
5. board-by-board turnover / continued accessibility;
6. disagreement turnover amount around or above `1bn CNY`;
7. often starts before the end of an index adjustment;
8. launch price below `10 CNY`, described as leaving more speculative room.

Several individual items are directly observable or numerically stated (`three-board launch`, `>=1bn CNY disagreement turnover`, `<10 CNY launch price`). Others are named but discretionary (`major theme`, `strong logic`, `news fermentation`, `index-adjustment end`).

## Why this is still not a machine-ready `absolute leader` definition

The source does **not** specify:

- whether all listed traits are mandatory, merely common, or alternatives;
- a deterministic score, ordering or precedence among the traits;
- how to select exactly one leader when several stocks satisfy overlapping traits;
- how to break ties;
- whether `absolute leader` in the W01 lower-volume passage is semantically identical to `market total leader` in this upper-volume section;
- the market-wide eligible universe and whether CSI800 is an acceptable substitute;
- a machine definition of “major theme,” “strong theme logic,” “continuing fermentation,” or “end of index adjustment”;
- how much history defines “historically high” volume;
- exact accessibility semantics for “board-by-board turnover”;
- the earliest causal timestamp at which the identity is considered known;
- whether a leader identity established only after first-wave disagreement may be retroactively attached to earlier launch/top rows.

The last point is critical for W01. A definition that uses future disagreement/turnover to label an earlier stock as “the leader” would introduce look-ahead if the W01 event is dated before that confirming information existed.

## Relationship to earlier V5 experiments

- **L01** is a descriptive board-stage proxy, not a unique market-total-leader classifier.
- **B01/B02/B03** tested narrow leader-related economic interpretations and did not establish a general leader identity standard.
- **U04** tested the exact `<10 CNY` launch-price trait as a modifier within a narrow context and was insufficient. Its outcome cannot be used to delete, strengthen or reweight that trait here.
- **W02** forbids substituting whichever historical leader proxy makes W01 profitable.

## Frozen readiness requirements

A future `absolute leader` preregistration needs all of the following before W01 returns:

1. `w01_to_market_total_leader_semantic_bridge` — justification that the upper-volume entity is the same target required by W01;
2. `eligible_universe` — market-wide / board-specific universe fixed causally;
3. `trait_set_transcription` — source trait list frozen without post-result edits;
4. `trait_necessity_or_combination_rule` — which traits are required and how they combine;
5. `major_theme_definition` — causal deterministic theme qualification;
6. `news_fermentation_definition` — causal deterministic information/attention qualification if used;
7. `historical_high_volume_window` — exact backward-only reference window if used;
8. `board_turnover_accessibility_rule` — deterministic accessibility/turnover semantics if used;
9. `index_adjustment_end_rule` — deterministic market-context rule if used;
10. `unique_selection_or_ranking_rule` — exactly how one leader is chosen;
11. `tie_break_rule` — deterministic handling of multiple candidates;
12. `identity_known_time` — earliest timestamp at which leader identity is allowed to affect a later W01 event;
13. `no_retroactive_identity_rule` — future confirmation cannot relabel an earlier decision as known at the time;
14. `independent_validation_or_source_basis` — no strategy-P&L choice of the above semantics;
15. `upstream_lineage_binding` — bind W02/M02 and source artifacts.

## Frozen decision

The source gives valuable leader **traits**, but not a unique causal leader **classifier**. Therefore W03 freezes:

`DEFER_ABSOLUTE_LEADER_PREREGISTRATION`

Allowed action:

`SOURCE_AND_REPRESENTATION_RESEARCH_ONLY`

Not allowed:

- turning all numbered traits into an AND rule merely because they appear in one list;
- choosing a subset/weight/rank from W01 or X02 returns;
- equating `highest board`, `largest return`, `largest turnover`, `sector leader` or L01 stage with the required absolute leader without independent pre-return justification;
- using future first-wave disagreement to retroactively identify a leader at an earlier decision date;
- reopening W01 P&L;
- changing X02, combining sleeves, paper trading or live trading.
