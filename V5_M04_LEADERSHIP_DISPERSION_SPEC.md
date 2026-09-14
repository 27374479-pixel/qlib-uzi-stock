# V5 M04 — source-grounded leadership-dispersion representation

## Purpose

M04 operationalizes one raw concept needed by the frozen `BULL_BROADENING_CONTEXT` ontology: whether strong activity is spread across multiple point-in-time industries or concentrated in one/few industries. It is a **representation audit only**.

The lower volume's true-bull discussion describes broader/multiple opportunity rather than dependence on one isolated hotspot. M04 therefore measures cross-industry dispersion of completed-close market strength without defining a bull/bear threshold and without using strategy returns.

## Frozen observables

For each completed trading date, using the point-in-time CSI800 panel and its as-of industry snapshots:

1. `known_industry_n` — number of non-UNKNOWN industries represented that day.
2. `positive_industry_n` — industries whose same-day cohort mean return is > 0.
3. `positive_industry_ratio` — `positive_industry_n / known_industry_n`.
4. `first_board_industry_n` — industries containing at least one completed first-board stock.
5. `seal_industry_n` — industries containing at least one completed sealed-limit stock.
6. `multi_board_industry_n` — industries containing at least one stock with completed board height >= 2.
7. `seal_top1_share` — largest industry's share of all sealed-limit stocks; 0 when no seals.
8. `seal_hhi` — Herfindahl concentration of sealed-limit stocks across industries; 0 when no seals.
9. `first_board_top1_share` — largest industry's share of all first-board stocks; 0 when none.
10. `first_board_hhi` — Herfindahl concentration of first-board stocks; 0 when none.
11. `multi_board_top1_share` — largest industry's share of all multi-board stocks; 0 when none.
12. `multi_board_hhi` — Herfindahl concentration of multi-board stocks; 0 when none.

No rolling window, fitted score, clustering, state label or strategy return enters M04.

## Structural validation

M04 can be `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_DISPERSION` only when:

- one row per date;
- all counts are nonnegative and industry counts do not exceed `known_industry_n`;
- ratios/shares/HHI values are finite and in [0,1];
- when event total is zero, corresponding top1 share and HHI are exactly zero;
- when event total is positive, `HHI <= top1_share <= 1`;
- future rows cannot change already-computed past-date values in unit tests;
- source industry assignments are point-in-time/as-of, not current-industry hindsight.

## Explicit prohibitions

M04 does not authorize:

- choosing a broadening threshold from X02/W01 performance;
- labeling dates `BULL_BROADENING_CONTEXT`;
- choosing HHI/top1 cutoffs from the historical distribution;
- changing X02;
- opening W01 P&L;
- portfolio combination;
- paper or live trading.

A later mapping experiment must be separately preregistered and independently validated.
