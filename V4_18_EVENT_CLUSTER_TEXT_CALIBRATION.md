# V4.18-B Event Cluster Text-Only Calibration

## Purpose

H04/H05 require dynamic event groups, but the semantic clustering threshold must not be selected by looking at X02 returns. V4.18-B therefore creates a separate **text-only calibration gate** between the causal event view and any performance research.

The sequence is:

```text
V4.17 canonical event lake
  -> V4.18-A causal event view + frozen market sessions
  -> V4.18-B text-only semantic calibration
  -> freeze cluster configuration/hash
  -> point-in-time cluster replay
  -> H04/H05 performance evaluation
```

No return, P&L, X02 outcome, industry performance, current concept membership, or later winner label is allowed in V4.18-B.

## Allowed inputs

The audit generator may read only these causal-event fields:

```text
event_id
instrument
stock_name
title
announcement_type
published_date
available_trade_date
causal_status
calendar_sha256
```

and the frozen V4.18 market-session artifact:

```text
data_lake/derived/v4_18_causal_events/market_sessions.parquet
```

It must not read price files or research-result files.

## Candidate text representation

The first candidate representation is deliberately simple and reproducible:

1. Unicode NFKC normalization;
2. lowercase ASCII;
3. remove the exact issuer short name when available;
4. normalize punctuation/whitespace;
5. remove only a small fixed boilerplate list used for text formatting, not economic semantics;
6. represent Chinese text with binary character 2-grams and 3-grams;
7. preserve ASCII/alphanumeric terms as whole tokens;
8. compare token sets with binary cosine similarity.

There is no corpus-fitted TF-IDF, no future vocabulary, no pretrained embedding call, and no web lookup. The representation therefore cannot learn from future market outcomes.

The representation may still prove inadequate. In particular, generic filing titles can look identical while not representing one economic theme. That failure must be exposed by text QA rather than hidden by a return-based workaround.

## Blind text audit

`v4_18_prepare_event_text_audit.py` produces deterministic review files without any return columns.

Pair labels are defined as:

- `SAME_CONTEXT`: the two titles plausibly describe the same economically meaningful event/theme context;
- `DIFFERENT_CONTEXT`: they do not, including cases that merely share a generic filing template;
- `AMBIGUOUS`: title text alone is insufficient.

Examples of generic filing similarity that should **not** automatically count as the same dynamic theme include unrelated issuers both publishing board resolutions, periodic reports, or routine governance notices.

The audit sample is stratified by similarity bands so reviewers see likely positives, hard negatives, and boundary cases. Sampling is deterministic from event IDs and does not use returns.

## Threshold freeze rule

The cluster similarity threshold is not hard-coded before text QA. It is frozen by `v4_18_freeze_event_cluster_config.py` only from decisive text labels (`SAME_CONTEXT` / `DIFFERENT_CONTEXT`).

Minimum calibration evidence:

```text
>= 200 decisive pair labels
>= 40 SAME_CONTEXT labels
>= 80 DIFFERENT_CONTEXT labels
```

Threshold candidates are predeclared:

```text
0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70
```

A candidate threshold must reach:

```text
precision >= 0.90
```

Among eligible thresholds, choose the one with the highest recall; ties are broken by higher precision and then the higher threshold.

If no threshold reaches the precision floor, calibration **fails**. The project must improve text normalization/theme eligibility using text-only evidence and rerun calibration. It must not lower the standard because a looser threshold helps X02 returns.

## Novelty lifecycle parameters

These lifecycle choices are fixed before performance evaluation and are not selected from P&L:

- `research_start_burn_in_sessions = 60`;
- `quiet_reset_sessions = 20`;
- session counting uses the persisted V4.18 market calendar;
- events during burn-in still seed semantic history, but H04 novelty classifications in that initial 60-session window are not eligible for performance claims;
- after more than 20 trading sessions with no event assigned to a semantic episode, a later matching event starts a new episode rather than pretending the old episode remained continuously active.

The 60-session burn-in prevents the 2021-01-01 data boundary from being mistaken for the birth of long-existing disclosure patterns. The 20-session quiet reset matches the already-preregistered H04 `RECENT = 6–20 trading days` horizon.

## Same-day causality and determinism

Date-precision events can become available on the same V4.18 `available_trade_date`. Their internal source order is not historically meaningful.

Therefore the production cluster builder must process each trade date as a batch and must not let arbitrary row ordering change cluster identity. Existing historical clusters may receive new members, but previously distinct historical clusters must never be retroactively merged in a way that changes earlier snapshots.

A replay test must prove that running through date D and then rerunning the full history produces identical assignments and point-in-time membership for all dates <= D.

## Freeze artifact

A successful text calibration writes a machine-readable freeze artifact containing at least:

```text
cluster_config_version
text_feature_version
similarity_metric
similarity_threshold
threshold_grid
precision
recall
labeled_pair_count
positive_label_count
negative_label_count
audit_sha256
research_start_burn_in_sessions
quiet_reset_sessions
calendar_sha256
```

The later cluster builder and H04/H05 research code must read this artifact. They must not silently substitute a threshold or lifecycle parameter from source code defaults.

## Scientific boundary

Text-only calibration answers only:

> “Do these titles group into defensible dynamic contexts without looking at returns?”

It does **not** answer:

> “Does the group predict X02 returns?”

That second question remains locked until V4.17-C, V4.17-D, V4.18-A, the text freeze, and point-in-time replay checks all pass.
