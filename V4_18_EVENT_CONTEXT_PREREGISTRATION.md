# V4.18 Point-in-Time Event Context Attribution — Preregistration

## Research question

V4.14–V4.16 showed that X02 `LIMIT_ADJUSTED_MOMENTUM` is not a micro-cap/illiquidity artifact, while coarse market, money-flow and static-industry regimes do not explain the 2021–2023 vs 2024–2026 sign change.

The next question is deliberately narrower than “invent another alpha”:

> Does a genuinely point-in-time **new-event / dynamic-cluster context** explain when the already-fixed X02 seed alpha works?

X02 stock ranking, entry, exit and costs stay unchanged. The event layer is tested first as an attribution/context variable, not as a new standalone trading score.

## Book provenance

- H04 `novelty-emergence`: new direction / new theme first diffusion.
- H05 `breadth-with-leader`: group breadth and core strength must coexist.
- Quant mapping: mainline/theme should prefer point-in-time event reason/context; static industry is only a weak fallback and has already failed as a stable substitute.

No event rule may be promoted merely because it improves historical holdout after inspection.

## Frozen X02 contract

The X02 definition is not re-optimized in this stage:

- formation signal uses the completed **T-1** daily bar;
- raw and clean 20-day momentum ranks >= 0.80;
- `hit_count20 <= 1`;
- the same executable filters already used in V4.x;
- **T** entry = 14:45 end-labelled 5m close;
- Top3 equal weight;
- **T+1 10:00** primary exit;
- BASE and CONSERVATIVE cost models unchanged.

The event layer may decide how to *attribute or filter* an already-fixed X02 candidate, but it may not change the X02 rank formula, entry clock, exit clock, or cost assumptions in the first H04/H05 test.

## Canonical event data contract

Primary event source for the first implementation is the canonical V4.17 Eastmoney notice archive collected through AKShare `stock_notice_report`.

CNINFO is a **second-source audit**, not the canonical backtest table.

The raw V4.17 source is date-precision and intentionally stores:

```text
timestamp_precision = date
causal_use_policy = NEXT_TRADING_DAY_ONLY
published_at = null
first_seen_at = null
```

V4.18 then materializes the derived causal field:

```text
available_trade_date = strictly next frozen A-share trading session after published_date
```

The frozen trading calendar comes from repository BaoStock daily equity data; a calendar-day `D+1` shortcut is forbidden.

Only V4.18 rows with:

```text
causal_status = AVAILABLE_NEXT_SESSION
available_trade_date <= decision_trade_date
```

are visible to the research logic.

No historical intraday notice timestamp is inferred. `retrieved_at` is ingestion provenance and must never be interpreted as historical first-seen time.

## Two clocks: formation vs execution

This preregistration distinguishes two causal clocks explicitly.

### X02 formation clock

The stock signal/ranking is fixed from information available through the **T-1 completed daily bar**. Event data is not allowed to alter this ranking retrospectively.

### Event-context decision clock

The actual X02 trade occurs on **T at 14:45**. For the primary H04/H05 attribution/filter test, event documents may be included when their V4.18 `available_trade_date <= T`.

Because date-only notices published on T-1 map conservatively to T, they may therefore participate in T's event context. Notices whose `published_date = T` map to T+1 and are forbidden for the T trade.

This is intentionally different from the stale rule “event context no later than T-1”: that rule would incorrectly discard notices published on T-1 that are safely known by T.

## Market-data cutoff for the first H04/H05 test

Even though the execution occurs at 14:45 on T, **all price-derived group/breadth/leader features in the first test are frozen at T-1 close**.

Allowed market inputs for first-test H04/H05 context:

- member T-1 daily return;
- member T-1 cross-sectional rank;
- group T-1 positive/negative breadth;
- historical daily state ending at T-1.

Forbidden in the first test:

- T 09:30–14:45 return;
- T intraday breadth;
- T VWAP/volume acceleration;
- T 14:45 ranking changes;
- T close;
- T+1 information.

This restriction isolates whether point-in-time event context explains the fixed X02 seed. A later, separately preregistered execution study may ask whether T intraday confirmation helps, but it must not be mixed into the first H04/H05 attribution result.

## Event-cluster construction invariants

Semantic clustering must be frozen and quality-audited **before any X02 return/P&L table is joined**.

Allowed inputs to cluster construction at decision date T:

- normalized title text from documents with `available_trade_date <= T`;
- source event/document identity;
- issuer/security mapping causally visible by T;
- previously visible event documents;
- deterministic text-processing configuration frozen before return analysis.

Forbidden inputs:

- future or same-future-bar returns;
- T intraday price action in the first attribution test;
- later concept membership;
- current Eastmoney concept constituents backfilled into history;
- static `industry_code` treated as a theme label;
- whether a stock later became a winner/leader;
- any threshold selected by looking at X02 P&L.

The clustering implementation must save its version/configuration/hash so the historical cluster stream can be replayed identically.

## Point-in-time cluster state

For each cluster and decision trade date T, save only cumulative state causally known by T:

- `cluster_first_available_trade_date` = earliest V4.18 availability date of any member document;
- `known_document_count`;
- `known_stock_count` = distinct securities causally mapped by T;
- `new_stock_count_today` = securities first becoming causally mapped on T;
- `age_trading_days` = frozen-market-session distance from first availability to T;
- append-only point-in-time member list;
- cluster-builder version/hash.

The historical member list is append-only. A security first discovered on a later date must never appear in an earlier snapshot.

Cluster age is measured from **availability**, not publication calendar date.

## H04 attribution: novelty / first emergence

Do not optimize a “magic event age.” Report the following predeclared bins at decision date T:

- `FIRST_SEEN`: `age_trading_days = 0`;
- `EARLY`: 1–5 trading days;
- `RECENT`: 6–20 trading days;
- `OLD`: >20 trading days;
- `NO_EVENT_CONTEXT`: candidate has no causally eligible cluster membership at T.

These are attribution bins. A bin is not automatically promoted because it has the best CAGR.

The book hypothesis predicts that genuinely new/early expanding clusters should be healthier contexts than repeatedly recycled old clusters.

## H05 attribution: breadth with a contemporaneously identifiable core

A cluster is `GROUP_FORMED` only when at least **2 distinct securities** are causally known by T. This is the minimum semantic definition of a group, not an optimized threshold.

For formed groups, compute using **T-1 completed daily data only**:

- `positive_ratio_t1` = fraction of causally known members with positive T-1 return;
- candidate T-1 return rank within the causally known group;
- `candidate_top_quartile_t1` = candidate is in the top quartile of same-group T-1 return rank.

The literal first-test breadth condition is:

```text
positive_ratio_t1 > 0.5
```

Do not search alternate cutoffs in the first test.

Do not use the legacy hand-weighted `role_score`, a future winner label, or post-T market extremeness to define the core.

## Primary predeclared confluence

The primary book-native H04/H05 confluence is fixed before performance evaluation:

```text
H04_EARLY = FIRST_SEEN or EARLY
AND GROUP_FORMED
AND positive_ratio_t1 > 0.5
AND candidate_top_quartile_t1 = true
```

Interpretation:

1. a causally known event cluster is new/early at T;
2. at least two securities are already causally associated with it;
3. the known group had majority-positive breadth by T-1 close;
4. the X02 candidate was already among the stronger members by T-1 close;
5. the X02 trade itself remains the fixed T 14:45 -> T+1 10:00 execution.

No T-day price feature is used to rescue this primary test.

## Required descriptive partitions

Regardless of the primary confluence result, report X02 under the full predeclared context table:

- `NO_EVENT_CONTEXT`;
- `FIRST_SEEN`;
- `EARLY`;
- `RECENT`;
- `OLD`;
- group not formed vs `GROUP_FORMED`;
- breadth <= 0.5 vs breadth > 0.5;
- candidate top-quartile vs non-top-quartile.

These partitions are diagnostic. They are not a license to promote whichever cell happens to be best.

## Primary falsification test

The event layer is not considered explanatory unless the **predeclared primary confluence** has the same economically useful direction in both periods:

1. development 2021–2023 BASE CAGR > 0;
2. development CONSERVATIVE CAGR >= 0;
3. 2024–2026 BASE CAGR > 0;
4. 2024–2026 CONSERVATIVE CAGR >= 0;
5. at least 20 active trading days in each period;
6. not dependent on the best 5% of trading days;
7. report exposure, MDD, win rate, turnover and yearly returns;
8. compare against the same fixed X02 portfolio without event context;
9. report the fraction of original X02 opportunities retained by the context filter.

If the confluence remains negative in 2021–2023 and positive only in 2024–2026, the event layer has **not** explained the structural break.

If the result appears positive only after changing age bins, breadth threshold, group minimum size, clustering parameters, or core definition after inspecting returns, it is exploratory and must not be reported as confirmation of H04/H05.

## Infrastructure gates before any performance evaluation

H04/H05 performance code must refuse to run until all of the following hold:

1. V4.17-C full 2021-01-01 .. 2026-07-16 event lake passes the canonical completeness/causality gate for the exact research window;
2. V4.17-D second-source audit is acceptable on sampled overlaps;
3. V4.18 causal event view is generated from that exact-window PASS and its manifest passes;
4. semantic cluster construction is frozen without X02 return data;
5. cluster point-in-time replay passes append-only membership tests;
6. every H04/H05 market feature has an explicit data cutoff no later than T-1 close for the first test.

Until then H04/H05 remain `EVENT_REQUIRED`, not validated alpha.

## Scientific status

This preregistration defines how event context will be tested; it does not claim the event layer is profitable.

The intended sequence is:

```text
V4.17-C full historical backfill + canonical gate
  -> V4.17-D second-source audit
  -> V4.18 causal availability view
  -> freeze/replay-test semantic clustering
  -> H04 attribution
  -> H05 breadth-with-core attribution
```

The first performance table must use these frozen definitions before any exploratory alternatives are examined.
