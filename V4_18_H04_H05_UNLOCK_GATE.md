# V4.18 H04/H05 Formal-Test Unlock Gate

## Purpose

`v4_18_h04_h05_unlock_gate.py` is the last machine-readable barrier before the **first formal** H04/H05 outcome test.

It does not compute or inspect returns. Its job is to prove that the upstream evidence chain is coherent, production-sized, causally valid, and bound to the preregistered research window before any H04/H05 result is visible.

The gate is deliberately strict. A smoke test, stale one-day manifest, old source-audit JSON, mismatched frozen calendar, changed cluster threshold, or modified replay artifact must leave H04/H05 blocked.

## Required evidence

```text
v4_18_h04_h05_prereg_v1.json
output/v4_17_full_backfill_gate.json
output/v4_17_event_source_audit.json
output/v4_18_causal_event_view_manifest.json
output/v4_18_event_cluster_freeze_v1.json
output/v4_18_cluster_replay_manifest.json
```

The replay manifest must also point to its frozen calendar, event-assignment and membership artifacts, and their recorded SHA-256 values must still match the files on disk.

## What must agree

### Preregistration

The root contract must still be `v4.18-h04-h05-prereg.1`, remain `PREREGISTERED_NOT_TESTED`, and continue to forbid parameter search in the primary test.

The event window is taken from the preregistration itself. For the current experiment it is:

```text
2021-01-01 .. 2026-07-16
```

### V4.17-C

The full-backfill gate must:

- cover exactly the preregistered event window;
- pass row-level and yearly completion validation;
- allow downstream H04/H05 research;
- have no failed years;
- show every research year as passed; and
- have one terminal provider result for every requested calendar date.

A one-day smoke PASS cannot unlock the experiment.

### V4.17-D

The second-source audit must use the canonical-aware loader introduced by the V4.17-D source-audit work. It must:

- be audit-only;
- never use the audit canonicalizer as a trading feature;
- have `source_loader_validation_pass=true`;
- have no canonical Eastmoney contract violations;
- actually inspect canonical annual Eastmoney files for every research year;
- contain non-empty canonical Eastmoney and CNINFO evidence; and
- observe at least one exact canonical cross-source notice match.

This is an integrity/audit requirement, not an alpha threshold. No minimum match-rate is introduced by this gate.

### V4.18-A/B/C

All stages must use exactly the same `calendar_sha256`.

V4.18-A must preserve strict next-session availability and must not fabricate an intraday publication timestamp or use a mutable live calendar.

V4.18-B must be market-blind, must not have read X02 returns, and must keep the frozen lifecycle:

```text
burn-in             = 60 frozen market sessions
quiet reset         = 20 frozen market sessions
same-day batching   = required
retroactive merge   = forbidden
```

The prospective assignment algorithm must have been frozen before any return join.

V4.18-C must be market-blind, use the same freeze version and threshold, preserve future-history and source-row-order invariance, and produce non-empty cluster episodes. Its recorded calendar/assignment/membership artifact hashes are checked again by the unlock gate.

## Output

On success the gate writes:

```text
output/v4_18_h04_h05_unlock_gate.json
```

with:

```text
scientific_status = READY_FOR_FIRST_FORMAL_H04_H05_TEST
experiment_unlock.h04_h05_allowed = true
```

On any failure it writes `scientific_status = BLOCKED`, records all detected failures, exits non-zero, and H04/H05 must not be run or inspected.

## Important boundary

Passing this gate does **not** mean H04/H05 works. It means only that the first formal falsification test is now allowed to occur under the already-frozen rules.

After the first formal result is observed, any parameter change is a new experiment/version and must not be presented as the untouched preregistered primary test.
