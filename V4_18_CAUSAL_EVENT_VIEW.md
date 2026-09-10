# V4.18 Causal Event View

## Purpose

V4.17 deliberately stores historical Eastmoney announcements at **date precision**. It does not fabricate an intraday `published_at`, and every historical row carries:

```text
causal_use_policy = NEXT_TRADING_DAY_ONLY
```

V4.18 turns that policy into a deterministic research field:

```text
available_trade_date = strictly next frozen A-share trading session after published_date
```

This is infrastructure, not an alpha model. V4.18 does **not** cluster themes, infer market narratives, calculate returns, rank stocks, or run H04/H05.

## Hard upstream gate

`v4_18_build_causal_event_view.py` refuses to run unless the supplied V4.17 full-backfill gate:

1. is a `v4.17-c.*` gate;
2. has `validation.pass = true`;
3. has `research_eligibility.h04_h05_allowed = true`;
4. has no failed years; and
5. has `requested_start` and `requested_end` **exactly equal** to the V4.18 event window.

The exact-window rule is deliberate. A one-day V4.17 smoke PASS must never unlock a 2021–2026 causal research view.

## Frozen market calendar

The trading calendar is reconstructed from already-frozen BaoStock daily equity parquet files under:

```text
data_lake/raw/baostock/equity_daily
```

No live exchange calendar, AKShare calendar, current website, or other mutable external service is used.

For each calendar date, V4.18 counts the number of distinct equity files that contain that date. A date is accepted as a market session only when the count is at least `--min-active-instruments` (default: 100). This protects against a single corrupt security file inventing a trading day.

V4.18 persists the accepted ordered session list as a first-class derived artifact:

```text
data_lake/derived/v4_18_causal_events/market_sessions.parquet
```

The artifact contains:

```text
trade_date
active_instruments
calendar_sha256
calendar_artifact_sha256
calendar_version
```

`calendar_sha256` hashes the ordered session-date list and is also written to every causal event row. `calendar_artifact_sha256` hashes `trade_date|active_instruments` for every accepted session, so the persisted calendar can be independently checked against its manifest.

Downstream event-cluster/H04/H05 code must consume this persisted calendar artifact. It must not independently reconstruct a different trading calendar.

## Availability states

Each event receives one of three states:

```text
AVAILABLE_NEXT_SESSION
NO_NEXT_SESSION_IN_FROZEN_CALENDAR
OUT_OF_RESEARCH_HORIZON
```

`OUT_OF_RESEARCH_HORIZON` is used only when `--research-end` is supplied and the strictly next session is later than that date.

The builder enforces:

```text
available_trade_date > published_date
```

for every materialized availability date. Same-day availability is forbidden because the raw historical source has no reliable intraday timestamp.

## Derived-data boundary

Raw V4.17 files remain source-faithful and unchanged. V4.18 writes:

```text
data_lake/derived/v4_18_causal_events/events.parquet
data_lake/derived/v4_18_causal_events/market_sessions.parquet
output/v4_18_causal_event_view_manifest.json
```

Important event columns are:

```text
available_trade_date
causal_status
availability_rule_version
calendar_sha256
```

The manifest records both calendar hashes and the path of the persisted session artifact.

## Production command

Run this only after the **full** 2021–2026 V4.17 gate is green:

```bash
python v4_18_build_causal_event_view.py \
  --start 2021-01-01 \
  --end 2026-07-16 \
  --research-end 2026-07-17
```

`--research-end` should match the frozen price-research horizon chosen for H04/H05; it is not inferred from today's date.

## Research unlock sequence

The intended sequence remains:

```text
V4.17-C full historical backfill + canonical gate
    -> V4.17-D second-source audit
    -> V4.18 causal availability view + frozen market-session artifact
    -> freeze event clustering / novelty rules using text-only QA
    -> H04
    -> H05
```

A successful V4.18 build proves only that event information is placed on a causally valid trading date and that all downstream stages can share one immutable session calendar. It is not evidence that an event signal is profitable.
