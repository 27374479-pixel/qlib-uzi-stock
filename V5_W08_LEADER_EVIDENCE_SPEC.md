# V5 W08 — source-grounded leader-evidence representation

## Purpose

W08 addresses a separate prerequisite for W01: how much of the book's **market-total-leader evidence** can be represented causally before any leader label or W01 return is allowed.

This is a structural representation audit only. It deliberately does **not** decide which stock is the total leader, rank candidates, define a top, or open W01 P&L.

## Source-grounded traits

The supplied upper volume's total-leader list explicitly includes:

- a sustained large-theme / strong-theme logic;
- continued news/message fermentation;
- a three-board start;
- first-wave disagreement accompanied by historical-high turnover/amount participation;
- board-by-board turnover with daily accessibility;
- disagreement amount of at least CNY 1bn;
- often starting before the end of an index adjustment;
- launch price below CNY 10 as providing more speculation room.

Only a subset can be represented mechanically from the current point-in-time daily panel without inventing extra data or thresholds.

## Frozen W08 observables

Per stock/date W08 records:

1. `board_height` — completed sealed-board streak height already known at that close.
2. `three_plus_board` — literal source flag `board_height >= 3`.
3. `one_word` — daily one-word sealed-board status from the existing causal limit model.
4. `accessible_board_proxy` — sealed board and not one-word. This is explicitly **our operational proxy** for daily accessibility, not a verbatim definition of 换手.
5. `streak_history_complete` — whether the currently visible sealed streak is observed from board 1 inside the W08 panel; prevents silently inferring earlier accessibility when the panel starts mid-streak.
6. `streak_all_accessible_proxy` — when streak history is complete, whether every visible sealed board in the current streak satisfied `accessible_board_proxy`.
7. `streak_launch_price` — preclose of the first sealed board in a fully observed current streak.
8. `launch_price_lt_10` — literal `< CNY 10` source flag, only when launch price is known.
9. `first_unsealed_after_3plus_proxy` — current row is not sealed and the immediately prior valid row had board height >= 3. This is a transparent conservative proxy for a first post-streak disagreement event, not a claim that every such row is the book's 第一波分歧.
10. `amount_cny` and `turnover_rate_pct` — raw completed-close participation observables.
11. `amount_ge_1bn` — literal source amount threshold, reported descriptively and not promoted to a buy condition.

## Intentionally unresolved source traits

W08 does **not** manufacture proxies for:

- sustained large-theme / strong-theme logic;
- continued news/message fermentation;
- exact meaning/history scope of `historical-high` disagreement amount;
- the end of an index adjustment and early leader start relative to it;
- the exact turnover requirement behind `板板换手`;
- market-total-leader identity when multiple high-board candidates coexist.

Those remain separate source/readiness problems. In particular, the current panel's finite preload must not be called the source's full `historical-high` amount without a separately justified history definition.

## Structural validation only

W08 may pass only if:

- one row exists per instrument/date;
- `three_plus_board` exactly matches `board_height >= 3`;
- `accessible_board_proxy` exactly matches sealed and not one-word;
- incomplete streaks never receive a launch price or all-accessible verdict;
- known streak launch prices come only from a causally observed first board;
- `launch_price_lt_10` exactly matches known launch price `< 10`;
- `first_unsealed_after_3plus_proxy` uses only the immediately preceding valid row;
- `amount_ge_1bn` exactly matches amount >= CNY 1bn when amount is finite;
- future rows cannot change already-computed past evidence rows in unit causality tests.

## Prohibitions

W08 does not authorize a leader score, leader rank, `leader=true` label, W01 return screen, top-anchor definition, X02 modification, portfolio combination, paper trading or live trading. U04's prior insufficient `<10 CNY` economic result is not revived; W08 keeps that literal only as descriptive source evidence.