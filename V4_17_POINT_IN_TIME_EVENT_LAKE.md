# V4.17 Point-in-Time Event Lake

## Purpose

This stage exists to support book-native H04/H05 research without substituting static industry labels or current concept membership for historical themes.

The research chain is:

`book idea -> historical event known at the time -> stock mapping known at the time -> subsequent market/theme/core response -> causal execution`

No event-derived alpha may be promoted if its historical availability cannot be demonstrated.

## Phase 1: archived A-share notices

Primary source: Eastmoney notice archive via AKShare `stock_notice_report(symbol="全部", date=YYYYMMDD)`.

Canonical storage:

`data_lake/raw/eastmoney/notices/YYYY/YYYY-MM-DD.parquet`

Each row contains:

- deterministic `event_id`;
- source and source dataset;
- security code/name;
- notice title/type;
- source event date;
- source URL;
- retrieval timestamp;
- query date and date-match audit flag;
- explicit point-in-time policy fields.

## Critical causality rule

The Eastmoney archive exposed through this endpoint provides a calendar date but not a historically trustworthy intraday publication timestamp.

Therefore:

- `timestamp_precision = day`;
- `same_day_usable = false`;
- a backtest may use a notice only when `trade_date > knowledge_date`;
- `retrieved_at_utc` records our archive retrieval time and MUST NOT be interpreted as the historical first-seen time;
- no same-day 09:30/14:45 trade may use an event whose only known timestamp is that same calendar date.

This rule intentionally sacrifices some potentially usable same-day information to eliminate look-ahead risk.

## What this does NOT solve

This first phase does not provide reliable historical concept membership or real-time news timestamps.

Forbidden shortcuts:

1. backfilling today's concept constituents into prior years;
2. treating static `industry_code` as a dynamic theme;
3. inferring an intraday publication time from a daily archive date;
4. using retrieval time as historical first-seen time;
5. selecting event keywords after viewing OOS returns and presenting them as a book rule.

## H04/H05 eligibility

Phase 1 notice data can support conservative event research beginning from the next trading session.

Before H04/H05 can be promoted, a later research stage must preregister:

- event-family construction derived from book logic;
- deterministic text normalization/clustering rules;
- event novelty horizon;
- point-in-time stock-to-event mapping;
- market/theme/core expansion definitions;
- development vs historical holdout split;
- BASE and CONSERVATIVE execution costs;
- minimum sample and robustness requirements.

No current concept membership may enter that historical mapping.

## Data quality

Collector requirements:

- atomic parquet writes;
- resumable per-calendar-day partitions, including weekends because notices can appear outside trading sessions;
- retry with backoff;
- schema validation;
- deterministic event IDs and duplicate checks;
- manifest under `data_lake/manifests/` for every collection run;
- failures must make CI fail rather than silently creating a complete-looking dataset.

## Rollout

1. Smoke-test a short historical date window.
2. Inspect row counts, schema, date-match rate, duplicates, and provider stability.
3. Only after the smoke test succeeds, backfill 2021-01-01 through 2026-07-17.
4. Cross-check a sample against a second source (preferably CNINFO) before using the archive for H04/H05 inference.
