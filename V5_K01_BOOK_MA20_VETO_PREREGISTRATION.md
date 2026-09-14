# V5 K01 preregistration — book-grounded 20-day moving-average direction veto

## Why this experiment exists

The user asked that V5 knowledge and algorithms be learned from the supplied books rather than invented from backtest diagnostics. In the supplied lower volume, the short/medium-term stock-selection section explicitly says that stocks whose **20-day moving-average direction is downward are not participated in**. The same section says selection should be combined with environment, theme, sentiment and safety, rather than one rule being a complete strategy. A nearby short-term-system passage describes mature short-term systems as commonly holding roughly 1–2 days.

K01 therefore does **not** invent a new alpha strategy and does not modify X02/B01/B02/B03. It asks one narrow question: is the book's literal `20日线方向往下的股均不参与` rule supported as a generic causal risk veto in point-in-time CSI800 data?

## Frozen operational translation

At each completed close T for every eligible point-in-time CSI800 stock:

- `MA20_T` is the arithmetic mean of the most recent 20 closes including T;
- `MA20_T-1` is the prior trading row's already-known MA20;
- **downward MA20** means `MA20_T < MA20_T-1`;
- **non-downward MA20** means `MA20_T >= MA20_T-1`;
- rows without both MA20 values are excluded.

There is deliberately **no slope threshold**, rank, optimizer, price filter, volume filter, market-regime filter, industry filter, or X02 condition. This is the literal sign of the 20-day-line direction only.

## Outcome protocol

- Universe: point-in-time CSI800 membership using the persisted daily data protocol already used by the source-grounded V5 screens.
- Earliest evaluated signal date: 2021-05-17.
- Development: 2021-05-17 through 2023-12-31.
- Historical-later: 2024-01-01 onward in available persisted data.
- Signal known at close T only.
- Entry proxy: next available trading-day open; existing locked-limit execution rules apply.
- Primary horizon: **2 trading days** after entry.
- Diagnostics: 1 and 5 trading days only.
- Fixed round-trip cost: **0.36%**.
- Bootstrap: 5,000 samples with seed 20260914, sampling at the signal-date level through the existing paired-difference implementation.

## Primary comparison

- `selected`: non-downward MA20 rows.
- `control`: downward MA20 rows.
- Compare same-date cross-sectional mean executable returns so broad market days are paired rather than confused with the stock-level rule.

K01 is a **veto test**, not a buy-signal test. Therefore it does not require the selected cohort itself to make positive absolute returns after a 2-day holding period. Instead, the source claim is supported only when the downward-MA20 cohort is persistently worse.

## Frozen qualification gate

K01 is `VALIDATED_AS_RISK_VETO` only if **both** historical segments satisfy all of the following on the 2-day primary horizon:

1. selected executable observations >= 1,000;
2. control executable observations >= 1,000;
3. selected and control each have >= 200 active dates;
4. selected-vs-control same-date paired dates >= 200;
5. selected-minus-control paired mean return difference > 0;
6. paired bootstrap 95% lower bound > 0;
7. downward-MA20 control mean market excess < 0.

If coverage is insufficient, status is `INSUFFICIENT`. If coverage is sufficient but any directional condition fails, status is `NOT_VALIDATED`.

## Interpretation boundary

A pass means only that the supplied-book MA20-down rule has earned status as a **candidate risk veto for future, separately preregistered source-grounded experiments**. It does not authorize retroactively changing X02, B01, B02 or B03; it does not authorize a portfolio, paper trading, live trading, threshold search or a new entry strategy.

A failure is frozen. We will not rescue it by trying 18/19/21/30/45-day moving averages, multi-day slope windows or slope thresholds inside K01. Any other moving-average concept requires a separately sourced and preregistered experiment.
