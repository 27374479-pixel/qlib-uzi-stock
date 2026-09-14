# V5 W02 frozen result — W01 leader / top source readiness

## Outcome

**Status:** `DEFER_W01_EVENT_PREREGISTRATION`

**Allowed action:** `SOURCE_AND_REPRESENTATION_RESEARCH_ONLY`

W02 stops before constructing a W01 event and before inspecting any W01 strategy returns.

## What the source fixes directly

The primary lower-volume passage fixes a strong event skeleton:

- bear-market / weak-market context is required;
- the target must be an absolute/true leader;
- the opportunity is the first one after that leader tops;
- elapsed window is approximately `3–7` trading sessions;
- decline magnitude is approximately `20%–25%`.

The `3–7` and `20%–25%` numbers are frozen source parameters and may not be shifted after seeing returns.

## What remains unresolved

The source does not provide a machine-ready rule for:

- validated bear-state handoff — M02 is still deferred;
- unique point-in-time absolute-leader identity;
- prior-wave qualification;
- exact top price and causal top-confirmation rule;
- first post-top event/reset semantics;
- whether the 20%–25% decline is high-to-close, high-to-low, close-to-close, adjusted or unadjusted;
- causal decision/execution time;
- handling later highs, repeated setups and overlapping tops;
- an independent non-P&L basis for those discretionary choices.

Therefore the literal event shape is source-ready, while event identity is not.

## Technical verification

Final workflow run after ledger freeze: `34816191709`

- unit tests: **6 passed**;
- fail-closed decision verification: passed;
- W02 source-review SHA-256: `2207267946f6c07a4b265e2e06a5ad7bcd5d9d78b84c1b5157909525a5057e72`;
- frozen M01 result SHA-256: `cff4365fb4d979facca5910d7c9e30162f13f80b3362d26f26492370f0f8d87b`;
- frozen M02 review SHA-256: `af44466e2189f0f92f527b2b8af3d7842ec5ec8d084b62a5303097e1d6f5ae1f`;
- frozen M02 result SHA-256: `9b544d40824bbe28235a0ece36daadfafcfb25ef6daeb210bf5a3d2e9d9da971`;
- frozen evidence-ledger SHA-256 at final audit: `2d47d53d8501e49e2e3cb2af6c49f0730fd428a2ad1fa406e1ce4ca3b2cda96c`;
- artifact: `v5-w02-leader-top-source-readiness`;
- artifact id: `10336386875`;
- ZIP SHA-256: `31cfd327a8998ef6fc8c17b45378d0861552b57a3034079fb14daba2eea74192`.

## Authorizations remain closed

The following remain false:

- W01 event-preregistration authorization under current evidence;
- W01 return-screen authorization;
- X02-change authorization;
- portfolio-combination authorization;
- paper-trading authorization;
- live-trading authorization.

Even a future W02 readiness pass would authorize only writing a **new separate W01 event preregistration**. It would not directly authorize a return screen.

## Next allowed research

Seek stronger source/independent representation evidence for `absolute leader`, prior-wave qualification, the causal top anchor, first-event reset semantics and the drawdown measurement basis. Do not choose any of those definitions by comparing W01 or X02 P&L.
