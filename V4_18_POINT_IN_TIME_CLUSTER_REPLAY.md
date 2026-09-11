# V4.18-C Point-in-Time Event Cluster Replay

## Purpose

V4.18-C turns the market-blind V4.18-B text freeze into an append-only historical stream of semantic event episodes. It is still infrastructure, not an alpha test: no price, return, P&L, X02 outcome, current concept membership, or future winner label may be read.

The stage consumes only:

```text
data_lake/derived/v4_18_causal_events/events.parquet
data_lake/derived/v4_18_causal_events/market_sessions.parquet
output/v4_18_event_cluster_freeze_v1.json
```

and writes:

```text
data_lake/derived/v4_18_clusters/event_assignments.parquet
data_lake/derived/v4_18_clusters/cluster_membership.parquet
output/v4_18_cluster_replay_manifest.json
```

Production execution remains blocked until the exact-window V4.17-C corpus, V4.17-D source audit, V4.18-A causal view, and V4.18-B text calibration are genuinely complete. The builder can be developed and replay-tested on synthetic text-only fixtures before those production gates open.

## Frozen prospective assignment rule

The assignment algorithm is frozen before any H04/H05 return join as:

```text
prospective_single_linkage_same_day_batch_v1
```

For each frozen A-share trading session in chronological order:

1. Read only events whose `available_trade_date` equals that session.
2. Normalize titles with the already-frozen `v4.18-b.text.1` representation.
3. Build same-day single-linkage connected components using the frozen pairwise similarity threshold.
4. Take a snapshot of clusters that existed **before the current session** and whose last event is no more than `quiet_reset_sessions` sessions old.
5. For each same-day component, calculate the maximum pairwise text similarity to each active historical cluster.
6. If no historical cluster reaches the frozen threshold, start a new episode.
7. If one or more historical clusters reach the threshold, attach the whole component to the one with the highest match. Exact score ties use lexical `cluster_id`.
8. Never merge two pre-existing historical clusters. A new bridge event may attach to one of them, but it may not rewrite their earlier identities or membership.
9. Apply all current-day assignments only after every current-day component has made its decision from the same day-start snapshot.

This rule deliberately favors causal reproducibility over globally optimal retrospective clustering. A retrospective connected-components or agglomerative solution would let a future bridge document merge clusters that were distinct at an earlier decision date.

## Quiet reset

The already-frozen lifecycle is:

```text
quiet_reset_sessions = 20
```

An episode remains attachable when:

```text
current_session_index - last_event_session_index <= 20
```

If the gap is greater than 20 sessions, a later similar event starts a new episode. The old episode remains unchanged.

## Burn-in

The already-frozen research-start burn-in is:

```text
research_start_burn_in_sessions = 60
```

Events inside the burn-in still seed semantic history. They are not deleted and do not start a second artificial history at session 61. The builder marks whether the burn-in has completed so H04 novelty claims cannot treat the left edge of the dataset as genuine theme birth.

## Point-in-time outputs

`event_assignments.parquet` stores the causal assignment visible after each event's same-day batch, including:

```text
event_id
instrument
available_trade_date
session_index
cluster_id
cluster_first_available_trade_date
cluster_first_session_index
age_trading_days
h04_age_bin_at_event
known_document_count_after_batch
known_stock_count_after_batch
new_stock_count_today
group_formed_after_batch
historical_attachment_similarity
burn_in_complete
builder_version
```

The H04 age labels follow the already-preregistered bins:

```text
FIRST_SEEN = 0
EARLY      = 1..5
RECENT     = 6..20
OLD        = 21+
```

`cluster_membership.parquet` is append-only and stores the first causal membership of each security in an episode. A security first observed at session T can never appear in a snapshot for a session before T.

Downstream H05 code may reconstruct `known_stock_count` at decision date T only from membership rows with:

```text
member_first_session_index <= T_session_index
```

It must not use final cluster size as a historical feature.

## Group formation boundary

V4.18-C may expose the preregistered semantic fact:

```text
GROUP_FORMED <=> known_stock_count >= 2
```

This does not read market returns. The later H05 fields `positive_ratio_t1` and candidate top-quartile strength remain outside this stage because they are price-derived and must be computed only from T-1 completed daily data.

## Replay invariants

Before production use, CI must prove all of the following on synthetic fixtures:

- shuffling source-row order does not change assignments;
- replaying only through date D and replaying the full future history produce identical assignments and membership for all rows visible by D;
- an event after more than 20 quiet sessions starts a new episode;
- same-day similar events can form a group without depending on row order;
- the 60-session burn-in boundary is session-based, not calendar-day based;
- tampered calendar hashes are rejected;
- a freeze not explicitly carrying this assignment contract is rejected;
- forbidden-looking return/P&L columns may exist in the input Parquet but are not read because the builder uses an explicit column allow-list.

## Scientific boundary

A successful V4.18-C replay proves only that semantic contexts can be reconstructed causally and reproducibly from information available at each historical decision date.

It does **not** prove that FIRST_SEEN/EARLY events, formed groups, breadth, leaders, or X02 trades are profitable. Formal H04/H05 performance evaluation remains blocked until every upstream gate is green.
