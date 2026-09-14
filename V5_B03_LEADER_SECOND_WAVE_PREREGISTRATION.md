# V5 B03 preregistration — market leader second-wave restart

## Source anchor

This is a new hypothesis derived before looking at B03 results from the user-supplied *48-trader* books. The upper volume explicitly names `龙二波` alongside `龙头首阴` and `龙回头` as tactics applicable to the market total leader. A nearby passage also describes the total leader ebbing for `两三天` before the market structure changes. B03 deliberately tests a literal, conservative daily proxy for that combination rather than retuning rejected B01/B02 diagnostics.

The book does **not** provide a machine-ready formula for `龙二波`. Therefore the translation below is an operational proxy, not a claim that these exact rules are verbatim book instructions.

## Frozen causal translation

For each stock, let `P` be a completed daily bar on which:

1. the stock closes at its price limit (`seal_up`), and
2. its consecutive sealed-board height equals the point-in-time CSI800 maximum board height on that same day, with ties allowed.

`P` is therefore the same minimal point-in-time market-leader concept used in B02, without volume, turnover, price, industry, regime, or X02 filters.

A **B03 selected restart** occurs only when all of the following are true:

- after `P`, the stock has exactly **2 or 3 consecutive non-sealed trading rows**;
- none of those intervening rows closes at the upper limit;
- the next row closes at the upper limit again (`seal_up=True`);
- that row is the **first reseal** after `P`;
- `P` had positive board height and was a point-in-time market-max-height leader.

The fixed 2–3-session interruption is chosen from the source phrase `总龙头退潮两三天` before any B03 result is inspected. The reseal is a deliberately strong daily confirmation proxy for `二波`/`回头`: we do **not** buy the initial fade.

## Primary control

The control must have the same structure:

- a prior sealed streak,
- exactly 2 or 3 non-sealed trading rows,
- first reseal on the current row,

but the prior sealed streak height was **below** the point-in-time market maximum board height on `P`.

This isolates whether prior *market-leader status* adds value to the same second-wave restart structure.

## Trading protocol

- Universe: point-in-time CSI800 membership already used by the source-grounded V5 screens.
- Earliest evaluated event date: 2021-05-17.
- Development segment: 2021-05-17 through 2023-12-31.
- Historical-later segment: 2024-01-01 onward in available persisted data.
- Signal is known only after the reseal-day close.
- Entry: next available trading-day open.
- If the entry session is upper-limit locked under the existing daily execution proxy, the order is unfilled.
- Primary holding horizon: **2 trading days** after entry.
- Diagnostic horizons: 1 and 5 trading days only.
- Fixed round-trip cost: **0.36%**.
- Bootstrap: 5,000 samples, fixed seed 20260914.

## Frozen qualification gate

B03 qualifies only if **both** the 2021–2023 development segment and the 2024+ historical-later segment satisfy all of these on the primary 2-day horizon:

1. selected executable observations >= 30;
2. selected active dates >= 20;
3. selected-vs-control same-date paired dates >= 15;
4. selected mean net return > 0;
5. selected mean market excess > 0;
6. selected-minus-control paired difference > 0;
7. paired bootstrap 95% lower bound > 0.

If coverage is insufficient, status is `INSUFFICIENT`. If coverage is sufficient but any performance gate fails, status is `REJECTED`. Only a full pass yields `QUALIFIED_FOR_MINUTE_REPLAY`.

## Prohibited post-result changes

B03 results do **not** authorize changing:

- the 2–3 session interruption,
- the market-max leader definition,
- the reseal confirmation,
- the 2-day primary horizon,
- costs,
- sample gates,
- or any eligibility filter.

Diagnostics may describe 2-day versus 3-day interruption, one-word history, market state, and calendar year, but they cannot be promoted into B03 eligibility after seeing results. Any such rule requires a separately sourced and preregistered B04+ experiment.

A pass permits only a separately preregistered minute-level execution study. It does not authorize portfolio combination, X02 retuning, paper/live trading, or production use.
