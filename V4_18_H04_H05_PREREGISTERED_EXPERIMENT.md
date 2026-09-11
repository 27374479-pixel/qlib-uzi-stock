# V4.18 First Preregistered H04/H05 Experiment

## Purpose

This stage is the first code path allowed to join the frozen X02 strategy with the V4.18 point-in-time event graph. It is intentionally **hard locked** behind `output/v4_18_h04_h05_unlock_gate.json`.

A red or missing unlock gate must stop the process before cluster, X02, price, return, P&L, daily, or minute research data are read.

The sequence remains:

```text
V4.17-C exact-window canonical backfill PASS
  -> V4.17-D canonical Eastmoney/CNINFO audit PASS
  -> V4.18-A causal availability + frozen market calendar PASS
  -> V4.18-B market-blind text calibration frozen
  -> V4.18-C append-only point-in-time replay PASS
  -> V4.18 H04/H05 unlock gate PASS
  -> this first formal preregistered experiment
```

Until the unlock artifact is green, there is no formal H04/H05 result.

## Frozen X02 execution

The runner reuses the V4.16/V4.3 implementation rather than creating a new strategy:

```text
signal: T-1 completed daily bar
X02 selected: raw_mom20_rank >= 0.80
              clean_mom20_rank >= 0.80
              hit_count20 <= 1
execution buffer: 0.5% below upper limit
ranking: T-1 clean_mom20_rank
portfolio: Top3 equal weight; require 3 executable names
entry: T 14:45 completed 5m close
exit: T+1 10:00 completed 5m close
costs: BASE and CONSERVATIVE from v4_3_long_only_portfolio.py
```

No T intraday price variable may alter H04/H05 context or the ranking. T 14:45 price/volume and limit state are used only for the already-existing execution feasibility checks.

## One context per candidate

A stock can belong to multiple historical event episodes by trade date T. The first formal test must not select whichever episode later produces the best return.

The rule is frozen before outcomes:

1. keep only cluster memberships whose `member_first_session_index <= T`;
2. for each eligible cluster, find its latest event session `<= T`;
3. choose the cluster with the most recent such event session;
4. if multiple clusters tie on that session, choose the lexical-smallest `cluster_id`.

This decision uses event chronology only.

The H04 age is then:

```text
T session index - chosen cluster first session index
```

with the already-preregistered bins `FIRST_SEEN`, `EARLY`, `RECENT`, `OLD`, and `NO_EVENT_CONTEXT`.

The first 60 frozen sessions are burn-in and are excluded from H04/H05 performance claims.

## H05 breadth and core

The event graph contains all A-share issuers, so H05 must not silently calculate breadth only on the CSI800 X02 universe.

For the chosen cluster at T:

- causally known members are those with `member_first_session_index <= T`;
- T-1 stock returns are read from `data_lake/raw/baostock/equity_daily`, the same frozen all-A-share daily lake used by V4.18-A to construct the market calendar;
- `positive_ratio_t1 = positive known-member returns / known_stock_count`;
- a known member with no T-1 return contributes no positive observation to that denominator;
- candidate group-return percentile is calculated only among causally known members with a valid T-1 return;
- `candidate_top_quartile_t1` means ascending average percentile rank `>= 0.75` and requires at least two priced group members.

The first-test primary confluence is unchanged:

```text
(FIRST_SEEN or EARLY)
AND GROUP_FORMED (>=2 known stocks)
AND positive_ratio_t1 > 0.5
AND candidate_top_quartile_t1
```

There is no threshold search.

## Confirmatory comparison

The runner reports:

- the same fixed X02 baseline without event filtering;
- the preregistered primary H04/H05 confluence;
- development 2021-2023 and later 2024-2026 periods;
- BASE and CONSERVATIVE costs;
- exposure, CAGR, MDD, win rate, yearly returns and turnover proxies from the fixed one-session round trip;
- retained X02 opportunity fraction;
- best-5%-active-day ablation.

For the confirmatory rule to pass, both periods need at least 20 active days, BASE CAGR must be positive, CONSERVATIVE CAGR must be non-negative, and those same sign criteria must survive removal of the best 5% active days.

Descriptive H04/H05 partitions may be inspected after the first result, but they cannot replace the preregistered primary confluence and still be called confirmation.

## CI / execution safety

PR and push CI execute only guard/unit tests. They do not run the formal historical result.

The CI guard deliberately supplies nonexistent cluster and market-data paths with a red unlock artifact and asserts that the runner fails specifically at the control-plane gate before any of those paths are inspected.

The real formal job is manual-only from `main` and additionally requires the dispatch confirmation string:

```text
RUN_FIRST_FORMAL_TEST
```

Even with that string, the runner still refuses to proceed unless the production unlock artifact itself is green.

Formal results are uploaded as workflow artifacts; the workflow does not rewrite the preregistration or automatically commit outcome-driven rule changes.
