# V5 B02 preregistration — market leader first-yin / dragon-return precursor

## Source anchor

The user-supplied *48位游资* upper volume explicitly states that the **market total leader** can use leader tactics including **龙头首阴、龙回头、龙二波**. The source names the setup but does not provide a numeric optimization grid. B02 therefore uses a non-parametric, point-in-time definition of “market leader” rather than searching thresholds after observing returns.

B01 is already frozen as an insufficient/rejected precursor screen. B02 is a distinct book hypothesis, not a retuning of B01.

## Frozen causal translation

At completed close `T`:

1. `T-1` must be a sealed-board day for the stock.
2. `T` must be the **immediately following first non-sealed negative-close day** (`ret1 < 0`). This is the literal daily proxy for “首阴”.
3. The stock is in the **selected** cohort only when its `T-1` consecutive sealed-board height equals the maximum consecutive sealed-board height observed across the point-in-time CSI800 universe on `T-1`. Ties are allowed. This is the frozen proxy for “市场总龙头”.
4. The **primary control** is the same first-yin event after a sealed-board streak, but the prior streak height is strictly below the market maximum on `T-1`.
5. No amount, turnover, price, one-word-board-history, sector, market-regime, or X02 condition is part of B02 eligibility. Those may only be reported as diagnostics. This avoids importing B01 conditions or post-result tuning into B02.

The signal is known only after close `T`. Entry is the next available open. If the next session is locked at the upper limit under the existing daily execution proxy, entry is unfilled.

## Fixed evaluation

- Universe: point-in-time CSI800 membership already used by the repository.
- Research start: 2021-05-17.
- Development segment: 2021-05-17 through 2023-12-31.
- Historical-later segment: 2024-01-01 onward, through the available persisted daily data.
- Primary holding horizon: **2 trading days after next-open entry**.
- Diagnostic horizons: 1 and 5 trading days.
- Round-trip cost: **0.36%**.
- Bootstrap samples: 5,000 by signal date.
- Seed: 20260914.
- No parameter search.
- No X02 retuning.

The 2-day horizon is retained from the source-grounded short-holding convention already fixed in the V5 line; it is not selected from B02 results.

## Qualification gate fixed before results

For **both** development and historical-later segments, B02 must have:

- at least 30 executable selected observations;
- at least 20 selected active signal dates;
- at least 15 same-date selected-vs-control paired dates;
- selected 2-day mean net return > 0 after the fixed 0.36% round-trip cost;
- selected 2-day mean market excess > 0;
- same-date selected-minus-control 2-day mean difference > 0;
- date-bootstrap 95% lower confidence bound of the selected-minus-control 2-day difference > 0.

If coverage is below the minima, status is `INSUFFICIENT`. If coverage is sufficient but any fixed profitability/relative-evidence criterion fails, status is `REJECTED`. Only a full pass may become `QUALIFIED_FOR_MINUTE_REPLAY`.

A pass authorizes only a separately preregistered minute-level execution/reclaim study. It does **not** authorize portfolio inclusion or live trading.

## Anti-overfitting boundary

After B02 results are observed, the following may not be changed to rescue B02: leader definition, first-yin definition, development/later split, 2-day primary horizon, 0.36% cost, minimum sample counts, or qualification criteria. A materially different translation (for example adding turnover, changing to two-board leaders, requiring a reclaim candle, or adding a market-state filter) must be registered as a new hypothesis ID.