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
- row/source validation: `output/v4_17_event_lake_validation.json`
- full-backfill gate: `output/v4_17_full_backfill_gate.json`

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

Only recognizable A-share equity code families are retained. Non-equity rows
are counted in the request ledger and not silently mapped into the equity event
lake. Shenzhen `200xxx` B-shares are explicitly excluded.

## Critical causality rule

The Eastmoney archive exposed through this endpoint provides a calendar date but
not a historically trustworthy intraday publication timestamp.

Therefore V4.17-A deliberately stores:

- `timestamp_precision = date`;
- `published_at = null`;
- historical `first_seen_at = null`;
- `causal_use_policy = NEXT_TRADING_DAY_ONLY`.

A backtest may use such a notice only from the **strictly next A-share trading
session after `published_date`**. No same-day 09:30, 14:45, close-auction, or
other intraday decision may consume it.

`retrieved_at` records when this repository ingested the archive. It MUST NOT be
interpreted as the historical first-seen time.

This rule intentionally sacrifices potentially usable same-day information to
eliminate look-ahead risk.

### Why raw data does not contain `available_at`

V4.17 deliberately does not invent an `available_at` timestamp for a source
that exposes date precision only. The raw archive remains source-faithful.

The downstream causal research view will materialize an
`available_trade_date` using a frozen historical A-share trading calendar:

`available_trade_date = strictly next trading session after published_date`

That derived field belongs in a curated/research layer, not in the raw source
archive. This separation prevents a derived timestamp from being mistaken for
source-observed historical evidence.

### Archive-query provenance

Every normalized row also records `archive_request_date`. The collector hard
fails if the source returns a row whose `published_date` differs from the date
used to query the archive. The validator independently recomputes this check
and reports `archive_date_match_rate`.

This prevents a provider endpoint that silently returns nearby-date records from
creating a false point-in-time history.

## Request coverage and reproducibility

The collector iterates **calendar dates**, not trading dates, because corporate
disclosures can appear on weekends or market holidays. Every request is
ledgered as `success`, `empty`, or `error`, including retries and retrieval
timestamps.

Long backfills use atomic writes and resume semantics. A date is considered
complete only after it has a terminal `success` or `empty` ledger record.
Unresolved provider errors make the official workflow fail.

The row-level validator fails on:

- missing requested calendar dates;
- duplicate event IDs;
- schema/source drift;
- malformed instruments or blank titles;
- date-precision rows that fabricate `published_at` or `first_seen_at`;
- any date-precision row not marked `NEXT_TRADING_DAY_ONLY`;
- any `archive_request_date != published_date` mismatch.

## V4.17-C Full Backfill Completion Gate

A smoke test or a single validated partition is not evidence that the full
2021-2026 corpus exists. H04/H05 remain blocked until
`v4_17_full_backfill_gate.py` passes for the exact frozen research horizon.

The gate independently checks every requested year and requires:

- the yearly Parquet partition to exist;
- the yearly request ledger to exist;
- every calendar date in that year's requested window to have a ledger row;
- every date to terminate as `success` or `empty`;
- zero unresolved provider errors;
- zero duplicate event IDs within a yearly partition;
- provenance URL coverage above the configured threshold (default 99%);
- date-precision rows to keep `published_at` and `first_seen_at` null;
- every date-precision row to remain `NEXT_TRADING_DAY_ONLY`;
- no derived/current concept or theme-membership columns in the raw archive;
- the upstream row-level V4.17 validator to PASS for exactly the same window.

The machine-readable result is written to
`output/v4_17_full_backfill_gate.json`. Its key research switch is:

`research_eligibility.h04_h05_allowed`

If false, formal H04/H05 research is blocked. The official GitHub Actions
workflow executes this gate before persisting a validated archive.

### Expected completion matrix

For the current frozen minute-research horizon the required matrix is:

| Year | Required window | Gate |
| --- | --- | --- |
| 2021 | 2021-01-01 .. 2021-12-31 | must PASS |
| 2022 | 2022-01-01 .. 2022-12-31 | must PASS |
| 2023 | 2023-01-01 .. 2023-12-31 | must PASS |
| 2024 | 2024-01-01 .. 2024-12-31 | must PASS |
| 2025 | 2025-01-01 .. 2025-12-31 | must PASS |
| 2026 | 2026-01-01 .. 2026-07-16 | must PASS |

The 2026-07-16 endpoint is intentional: it matches the currently frozen
minute-research horizon. Extending the market-data horizon requires extending
this event archive and rerunning both validators; it must not silently mix
unequal research windows.

## Theme-mapping leakage contract

V4.17 raw announcement data must not contain present-day concept membership or
other derived theme membership. In particular, current concept constituents
must never be backfilled into historical dates.

Later event/theme mappings must live outside the raw source archive and carry
point-in-time provenance such as `mapping_known_at`. A mapping is research-usable
only when its historical availability is itself demonstrable.

## What this does NOT solve

This first phase does not provide reliable historical concept membership or
real-time news timestamps. It is a source-specific archive and is not itself
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
next trading session, but only after the full-backfill gate passes.

Before H04/H05 can be promoted, the next research stage must preregister:

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

1. **V4.17-A infrastructure**: source-faithful collector and request ledger.
2. **V4.17-B smoke/source validation**: prove archive/date/PIT contracts on a
   small historical window.
3. **V4.17-C full backfill**: collect 2021-01-01 through 2026-07-16 and require
   every yearly completion gate to PASS.
4. **V4.17-D source audit**: cross-check a historical sample against a second
   source, preferably CNINFO, before treating source coverage as
   production-grade.
5. **V4.18 causal event view**: attach the strictly-next-session
   `available_trade_date` from the frozen market calendar, then preregister and
   build event clustering/novelty features.
6. **H04**: test whether X02 is stronger after genuinely new causal events.
7. **H05**: test whether theme diffusion/core formation materially improves
   X02 selection or execution.

If a later source provides trustworthy historical intraday publication
timestamps and revision history, store it as a separate source rather than
overwriting the conservative date-precision archive.
