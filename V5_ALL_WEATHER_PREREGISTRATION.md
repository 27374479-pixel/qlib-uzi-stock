# V5 All-Weather Baseline Preregistration

This document freezes the first V5 all-weather experiment **before the first V5 result is read**.

## Goal

Do not retune X02. Treat the already-frozen X02 strategy as one risk-on sleeve and test whether a causal market-regime router can reduce regime dependence by holding cash outside the risk-on state.

This first experiment is a capital-preservation baseline, not a claim that cash alone is a complete all-weather portfolio. Neutral and weak-market alpha sleeves, if later added, must be separate preregistered experiments.

## Frozen X02 sleeve

Use the exact `original_gate_CONSERVATIVE` next-record daily return series produced by the X02 execution-validation chain. The X02 signal, market gate, Top-3 selection, 0.5% limit buffer, next-record entry, next-session 10:00 exit, and conservative cost model are not changed.

## Causal regime state

The regime observed after signal date `T-1` close is mapped to trade date `T`. No `T` return, high, low, close, or future regime information may be used.

The daily market fields come from the repository's existing point-in-time market-state construction. Add one slow breadth feature:

- `breadth20` = 20-trading-day rolling mean of daily market breadth, minimum 15 observations.

Regimes are fixed as follows, using sign thresholds only:

- `RISK_ON`: `weak_market == False` AND `breadth5 > 0` AND `breadth20 > 0` AND `money_effect > 0`.
- `RISK_OFF`: `weak_market == True` OR `breadth20 <= 0`.
- `NEUTRAL`: every other fully observed state.
- If required regime inputs are unavailable, classify as `NEUTRAL` and hold cash.

The precedence is `RISK_OFF` first, then `RISK_ON`, then `NEUTRAL`.

## Allocation rule for V5 baseline

- `RISK_ON`: 100% of the frozen X02 sleeve.
- `NEUTRAL`: 100% cash.
- `RISK_OFF`: 100% cash.

There is no leverage, no partial sizing, no replacement strategy, no threshold grid, and no parameter search in this first baseline.

## Evaluation

Report the frozen X02 sleeve and routed V5 baseline side by side for:

- full available history,
- 2021-2023 development/counterexample segment,
- 2024+ historical-later segment.

Report CAGR, total return, Sharpe, corrected max drawdown including the initial 1.0 equity point, active/exposure days, calendar-year returns, regime-day counts, regime transition counts, and X02 active-day returns by regime for diagnostics.

The 2024+ period is **not pristine out-of-sample** because it has already been inspected during X02 development. All V5 historical results are therefore research/development evidence only.

## Interpretation rule

The first question is narrow: can a simple causal regime router materially reduce X02's known regime dependence without changing X02 itself?

Do not change this regime definition after reading the first result. If the cash baseline is insufficient, the next step is a new preregistered neutral/weak-market sleeve experiment (for example an independently validated reversal or overnight-information sleeve), not threshold retuning of this router.

No result from this experiment authorizes live trading.