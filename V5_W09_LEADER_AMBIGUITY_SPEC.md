# V5 W09 — leader-candidate ambiguity representation

## Purpose

W08 established a causal per-stock representation for the subset of upper-volume market-total-leader traits that can be observed without inventing thresholds. W09 addresses one unresolved semantic problem from that source: **multiple stocks can carry strong leader evidence at the same completed close, while the book does not give a deterministic tie/identity rule.**

W09 is therefore a structural ambiguity audit only. It does not decide which stock is the leader, does not create a leader score/rank, and does not inspect W01/X02 returns.

## Source boundary

The supplied upper volume explicitly discusses a `market total leader` and lists traits including a three-board start, board-by-board accessibility, strong-theme/news context, first disagreement participation, CNY 1bn+ disagreement amount, early start near the end of index adjustment, and launch price below CNY 10. The source does not say that the stock with the largest completed board height is automatically the total leader, nor how ties should be resolved.

Accordingly, W09 uses market-maximum completed board height only as a **descriptive candidate-set lens**, not as a leader definition.

## Frozen date-level observables

For each completed trading date, using only W08 evidence available at that close:

- `sealed_evidence_n`: number of sealed-board evidence rows;
- `max_board_height`: maximum completed sealed-board height, zero if none;
- `max_board_candidate_n`: number of sealed rows tied at that maximum height;
- `three_plus_candidate_n`: number of sealed rows with board height >= 3;
- `complete_three_plus_candidate_n`: three-plus rows with a fully observed current streak;
- `accessible_three_plus_candidate_n`: fully observed three-plus rows whose visible streak is accessible under the frozen W08 proxy;
- `launch_lt10_three_plus_known_n`: three-plus rows with known launch-price comparison;
- `launch_lt10_three_plus_true_n`: three-plus rows with known launch price < CNY 10;
- `first_unsealed_after_3plus_n`: conservative W08 first-unsealed-after-3plus proxy rows;
- `max_board_tie`: whether `max_board_candidate_n > 1`;
- `three_plus_multiplicity`: whether `three_plus_candidate_n > 1`.

No candidate is promoted by these counts. The `<10` flag remains descriptive because U04 was insufficient economically.

## Structural validation

W09 may return `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_LEADER_AMBIGUITY` only if:

- there is one row per date;
- all counts are nonnegative integers;
- max-board candidates are a subset of sealed evidence rows;
- three-plus candidates are a subset of sealed evidence rows;
- complete/accessibility/launch-price counts are nested within three-plus candidates as defined;
- tie flags exactly match their arithmetic count definitions;
- future W08 rows cannot alter already computed past date rows in the unit causality test.

## Prohibitions

W09 does not authorize:

- `max board = leader`;
- choosing among tied candidates;
- a trait-weighted leader score;
- filtering W01 by whichever candidate count later has better returns;
- resolving theme/news or historical-high-participation semantics from sample frequencies;
- top-anchor construction;
- W01 return screening;
- X02 changes;
- portfolio combination;
- paper or live trading.

A later identity experiment must preregister its tie, scope, persistence and independent validation rules before any strategy P&L is used.