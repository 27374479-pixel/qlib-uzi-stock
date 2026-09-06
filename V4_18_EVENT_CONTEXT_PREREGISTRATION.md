# V4.18 Point-in-Time Event Context Attribution — Preregistration

## Research question

V4.14–V4.16 showed that X02 `LIMIT_ADJUSTED_MOMENTUM` is not a micro-cap/illiquidity artifact, while coarse market, money-flow and static-industry regimes do not explain the 2021–2023 vs 2024–2026 sign change.

The next question is deliberately narrower than “invent another alpha”:

> Does a genuinely point-in-time **new-event / dynamic-cluster context** explain when the already-fixed X02 seed alpha works?

X02 stock ranking, entry, exit and costs stay unchanged. The event layer is tested first as an attribution/context variable, not as a new standalone trading score.

## Book provenance

- H04 `novelty-emergence`: new direction / new theme first diffusion.
- H05 `breadth-with-leader`: group breadth and core strength must coexist.
- Quant mapping: mainline/theme should prefer point-in-time event reason/concept; static industry is only a weak fallback and has already failed as a stable substitute.

No event rule may be promoted merely because it improves the historical holdout after inspection.

## Data availability contract

Canonical source for the first implementation: V4.17 CNINFO notice event lake.

Every row must carry:

- `source_event_id`: document-level source identity when available;
- `event_id`: document-security mapping identity;
- `security_code` / `instrument`;
- `published_date`;
- `eligible_from_date`;
- `event_time_precision`;
- `knowledge_policy`.

Only records with `eligible_from_date <= signal_date` are visible to the model.

Date-only notices use the conservative policy:

`published date D -> earliest eligible date D+1 calendar day`.

No intraday publication time is inferred.

## Event-cluster construction invariants

The semantic-clustering implementation must be frozen and quality-audited **before any market-return table is joined**.

Allowed inputs to cluster construction:

- title text already visible by `eligible_from_date`;
- source event/document identity;
- issuer/security mapping already visible at that time;
- previously visible event documents.

Forbidden inputs:

- future or same-future-bar returns;
- later concept membership;
- current Eastmoney concept constituents backfilled into history;
- static `industry_code` treated as a theme label;
- whether a stock later became a winner/leader;
- any threshold selected by looking at X02 P&L.

The clustering code must save its own version/hash so clusters can be replayed identically.

## Point-in-time cluster state

For each cluster and signal date, save only cumulative state known by that date:

- `cluster_first_seen_date` = earliest eligible date of any member document;
- `known_document_count`;
- `known_stock_count` = distinct securities causally mapped by then;
- `new_stock_count_today`;
- `days_since_first_seen`;
- point-in-time member list.

The historical member list is append-only. A security discovered on a later date must not appear in an earlier snapshot.

## First test: context attribution on fixed X02

The X02 definition remains unchanged:

- T-1 completed daily signal;
- raw and clean 20-day momentum ranks >= 0.80;
- `hit_count20 <= 1`;
- same executable filters already used in V4.x;
- T entry = 14:45 end-labelled 5m close;
- Top3 equal weight;
- T+1 10:00 primary exit;
- BASE and CONSERVATIVE cost models unchanged.

Event context is attached using information visible no later than T-1.

### H04 attribution

Do not optimize a “magic event age.” Report predeclared descriptive bins based on cluster age at T-1:

- `FIRST_SEEN`: age 0 trading days;
- `EARLY`: age 1–5 trading days;
- `RECENT`: age 6–20 trading days;
- `OLD`: age >20 trading days;
- `NO_EVENT_CONTEXT`: X02 candidate has no eligible cluster membership.

These bins are for attribution. A bin is not automatically promoted because it has the best CAGR.

The book hypothesis predicts that genuinely new/early expanding clusters should be healthier than repeatedly recycled old contexts.

### H05 attribution

A cluster is called `GROUP_FORMED` only when at least 2 distinct securities are causally known by T-1. This is the minimum definition of a group, not an optimized threshold.

For formed groups, report separately:

- group breadth on T-1 (`positive_ratio`);
- candidate cross-sectional strength within the causally known group;
- whether the candidate is in the top quartile of same-group T-1 return rank;

`positive_ratio > 0.5` is the literal “majority positive” semantic comparison; do not search alternate cutoffs in the first test.

Do not use the legacy hand-weighted `role_score`.

## Primary falsification test

The event layer is not considered explanatory unless a **predeclared book-native confluence** shows the same direction in both periods:

`EARLY_OR_FIRST + GROUP_FORMED + majority positive + candidate top-quartile within group`.

Required evidence before any gate can be considered:

1. development 2021–2023 BASE CAGR > 0;
2. development CONSERVATIVE CAGR >= 0;
3. 2024–2026 BASE CAGR > 0;
4. 2024–2026 CONSERVATIVE CAGR >= 0;
5. at least 20 active trading days in each period;
6. not dependent on the best 5% of trading days;
7. report exposure, MDD, win rate and yearly returns;
8. compare against the same fixed X02 portfolio without event context.

If the confluence is still negative in 2021–2023 and positive only in 2024–2026, the event layer has **not** explained the structural break.

## Scientific status

V4.18 cannot begin performance evaluation until:

1. V4.17 full event lake passes completeness and causal checks;
2. cross-source audit is acceptable on sampled overlaps;
3. semantic cluster construction is frozen without return data;
4. cluster point-in-time replay passes append-only membership tests.

Until then H04/H05 remain `EVENT_REQUIRED`, not validated alpha.
