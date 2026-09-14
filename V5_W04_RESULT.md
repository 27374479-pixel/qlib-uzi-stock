# V5 W04 frozen result — W01 top anchor and drawdown basis

## Outcome

**Status:** `DEFER_TOP_ANCHOR_PREREGISTRATION`

**Allowed action:** `SOURCE_AND_REPRESENTATION_RESEARCH_ONLY`

W04 stops before any W01 return screen. The supplied source fixes the event order and approximate shape, but not the causal price/time semantics required to know that a leader has topped and to measure the subsequent decline without discretionary choices.

## Source-fixed facts preserved

- event order: `leader_top -> decline -> first_left_side_opportunity`;
- elapsed interval: approximately `3–7` trading sessions;
- decline magnitude: approximately `20%–25%`.

These literals may not be moved to create more samples or better returns.

## Missing machine semantics

The reviewed source does not fix:

- top price field: intraday high, close, adjusted swing high, board-cycle high, or another anchor;
- raw/adjusted-price and corporate-action treatment;
- preceding-wave anchor scope;
- causal top-confirmation rule and the timestamp when the top becomes known;
- top-day/day-1 counting convention for the 3–7-session clock;
- post-top observation field and exact drawdown formula;
- exact mechanical interpretation of the source's approximate 20%–25% wording;
- first-qualifying-event and later-new-high reset rules;
- suspension/missing-session treatment;
- first causal decision/entry time;
- an independent non-P&L validation basis for those choices.

A nearby trend-stock rule about three days without a new intraday high is intentionally **not transferred** into W01. It is an exit heuristic for a different prerequisite state and would change the W01 event clock.

## Technical verification

Workflow run: `34817132686`

- unit tests: **6 passed**;
- fail-closed verification: passed;
- source review SHA-256: `56c3032f2f5d42ef0ce5ad0a43f367ff835e1e324939e335fe33e86e38559fb3`;
- W03 result SHA-256: `7fea9943311fb68cdf8a732515cd29d29017a04d5726992b4effad531fa8f290`;
- W02 result SHA-256: `12e7d0bd52b9731765d44e7844be94b5fe16e3cf4c5d7e6b0dfd6f3ed02f8709`;
- M02 result SHA-256: `9b544d40824bbe28235a0ece36daadfafcfb25ef6daeb210bf5a3d2e9d9da971`;
- evidence ledger SHA-256 at audit time: `e6459d0a34c64d7ab42c57c8fca9896c6feac6ae3dfe92c8ec7cc3b8a6fff4bf`;
- artifact: `v5-w04-top-anchor-source-readiness`;
- artifact id: `10337410398`;
- ZIP SHA-256: `05cc6948ec1aaabfdd1ff4a51e9a4f2c1a9e0be2e2a75a21c2e6d77ff4010dca`.

## Authorizations remain closed

- top-anchor preregistration: false under current evidence;
- W01 event preregistration: false;
- W01 return screen: false;
- X02 change: false;
- portfolio combination: false;
- paper trading: false;
- live trading: false.

Even a future W04 readiness pass would authorize only a separate preregistration of the top/drawdown semantics. It would not by itself authorize W01 P&L because the upstream bear-state and absolute-leader gates remain deferred.
