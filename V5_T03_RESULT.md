# V5 T03 frozen result — trend-stock entry/risk literals

## Outcome

**Status:** `DEFER_TREND_ENTRY_PREREGISTRATION`

**Allowed action:** `SOURCE_AND_TREND_STATE_REPRESENTATION_ONLY`

The lower-volume source supplies unusually concrete trend-stock numbers — a 12-session moving-average line for low-buy, caution after breaking the 20-session line, and an acute selloff around 20% as a possible good buy area — but it does not define the prerequisite trend state or the causal event/execution semantics well enough for a return screen.

## Source-fixed literals preserved

- `low_buy_ma_period_sessions = 12`;
- `caution_ma_period_sessions = 20`;
- `acute_selloff_fraction_approx = 0.20`.

These values may not be moved or replaced with neighboring periods/percentiles to create a better result.

## Missing machine semantics

The source does not currently fix:

- a deterministic `trend_stock` prerequisite;
- adjusted/raw price and MA calculation basis;
- MA12 touch/near/cross/reclaim semantics and entry timing;
- MA20 break observation semantics and what `caution` means operationally;
- the anchor, formula and time window for the ~20% acute selloff;
- interaction/precedence among MA12, MA20 and acute-selloff conditions;
- sizing, stop, holding horizon, exit and re-entry;
- an independent non-P&L basis for those choices.

## Technical verification

Workflow run: `34829455611`

- unit tests: **7 passed**;
- fail-closed verification: passed;
- source review SHA-256: `afb0b04d7fe8032bca5e4e578a0745bb570cf8adc6698d8ed974edf9346cb38b`;
- T02 result SHA-256: `8e414b8b782eb8ddc4770dc38a31e1b317134f401b3385281b470eacdc615815`;
- artifact: `v5-t03-trend-entry-source-readiness`;
- artifact id: `10341428257`;
- ZIP SHA-256: `830e1feaa0e417d6e5ae6bc71775325d1ddfc6682748d7742ec4bf40aee779f0`.

## Authorizations remain closed

- trend-entry preregistration: false under current evidence;
- trend return screen: false;
- T02+T03 combination: false;
- X02 change: false;
- portfolio combination: false;
- paper trading: false;
- live trading: false.

A future T03 readiness pass would authorize only a separate trend-entry preregistration. It would not by itself authorize P&L or combining the entry literals with T02 exits.
