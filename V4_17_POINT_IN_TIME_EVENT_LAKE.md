# V4.17 Point-in-Time Event Lake

## Purpose

This stage exists to support book-native H04/H05 research without substituting
static industry labels or current concept membership for historical themes.

The research chain is:

`book idea -> historical event known at the time -> stock mapping known at the time -> subsequent market/theme/core response -> causal execution`

No event-derived alpha may be promoted if its historical availability cannot be
demonstrated.

## Phase 1: archived A-share notices

Primary source: Eastmoney notice archive via AKShare
`stock_notice_report(symbol="全部", date=YYYYMMDD)`.

Canonical storage:

- events: `data_lake/raw/eastmoney/notices/year=YYYY/notices_YYYY.parquet`
- request ledger: `data_lake/manifests/v4_17_eastmoney_notice_requests_YYYY.csv`
- validation: `output/v4_17_event_lake_validation.json`

The event Parquet path is already covered by repository Git LFS rules.

Each normalized event contains:

- deterministic `event_id`;
- source provider and endpoint;
- `archive_request_date`, recording the calendar date used to query the archive;
- security code/name;
- notice title/type;
- source `published_date`;
- source URL;
- ingestion `retrieved_at`;
- explicit timestamp precision and causal-use policy;
- deterministic raw-payload hash.

Only recognizable A-share equity code families are retained.  Non-equity rows
are counted in the request ledger and not silently mapped into the equity event
lake.  Shenzhen `200xxx` B-shares are explicitly excluded.

## Critical causality rule

The Eastmoney archive exposed through this endpoint provides a calendar date but
not a historically trustworthy intraday publication timestamp.

Therefore V4.17-A deliberately stores:

- `timestamp_precision = date`;
- `published_at = null`;
- historical `first_seen_at = null`;
- `causal_use_policy = NEXT_TRADING_DAY_ONLY`.

A backtest may use such a notice only from the next A-share trading session.  No
same-day 09:30, 14:45, or other intraday decision may consume it.

`retrieved_at` records when this repository ingested the archive.  It MUST NOT
be interpreted as the historical first-seen time.

This rule intentionally sacrifices potentially usable same-day information to
eliminate look-ahead risk.

### Archive-query provenance

Every normalized row also records `archive_request_date`.  The collector hard
fails if the source returns a row whose `published_date` differs from the date
used to query the archive.  The validator independently recomputes this check
and reports `archive_date_match_rate`.

This prevents a provider endpoint that silently returns nearby-date records from
creating a false point-in-time history.

## Request coverage and reproducibility

The collector iterates **calendar dates**, not trading dates, because corporate
disclosures can appear on weekends or market holidays.  Every request is
ledgered as `success`, `empty`, or `error`, including retries and retrieval
timestamps.

Long backfills use atomic writes and resume semantics.  A date is considered
complete only after it has a terminal `success` or `empty` ledger record.
Unresolved provider errors make the official workflow fail.

The validator also fails on:

- missing requested calendar dates;
- duplicate event IDs;
- schema/source drift;
- malformed instruments or blank titles;
- date-precision rows that fabricate `published_at` or `first_seen_at`;
- any date-precision row not marked `NEXT_TRADING_DAY_ONLY`;
- any `archive_request_date != published_date` mismatch.

## What this does NOT solve

This first phase does not provide reliable historical concept membership or
real-time news timestamps.  It is a source-specific archive and is not itself
proof of complete exchange-level disclosure coverage.

Forbidden shortcuts:

1. backfilling today's concept constituents into prior years;
2. treating static `industry_code` as a dynamic theme;
3. inferring an intraday publication time from a daily archive date;
4. using retrieval time as historical first-seen time;
5. selecting event keywords after viewing OOS returns and presenting them as a
   book rule.

## H04/H05 eligibility

Phase 1 notice data can support conservative event research beginning from the
next trading session.

Before H04/H05 can be promoted, a later research stage must preregister:

- event-family construction derived from book logic;
- deterministic text normalization/clustering rules;
- event novelty horizon;
- point-in-time stock-to-event mapping;
- market/theme/core expansion definitions;
- development vs historical holdout split;
- BASE and CONSERVATIVE execution costs;
- minimum sample and robustness requirements.

No current concept membership may enter historical mapping.

## Rollout

1. Smoke-test a short historical date window and enforce the source schema/date
   contract.
2. Backfill 2021-01-01 through 2026-07-16, matching the currently persisted
   minute-research horizon.
3. Run the strict full-window validator; only a PASS permits H04/H05 work.
4. Cross-check a historical sample against a second source, preferably CNINFO,
   before treating source coverage as production-grade.
5. If a later source provides trustworthy historical intraday publication
   timestamps and revision history, store it as a separate source rather than
   overwriting the conservative date-precision archive.
