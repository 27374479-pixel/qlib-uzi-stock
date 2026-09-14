# V5 L01 — leader-stage proxy specification

## Purpose

This is a **representation audit, not an alpha test**. The supplied lower 48-trader volume lists a rough leader evolution in this order:

`启动 -> 确认 -> 发酵 -> 加速 -> 分歧 -> 反包 -> 龙回头`

The book does not provide a machine-ready daily definition for every stage. L01 therefore freezes one deliberately simple point-in-time proxy and asks only whether the repository's existing daily event fields can represent these named states consistently enough for later descriptive research.

No return, entry, exit, portfolio, ranking, optimization, paper-trading or live-trading conclusion is authorized by this audit.

## Source boundary

Primary source: user-supplied `48位游资-下册`, PDF page 123/227 (printed page 92), which explicitly lists the seven-stage sequence above.

A nearby upper-volume passage separately mentions `总龙头退潮两三天` and `龙回头/龙二波`. That separate source is used only to make the L01 `龙回头` proxy's 2/3-session interruption explicit. It must not be represented as if page 123 itself gave that numeric rule.

## Frozen operational proxy

All definitions use completed daily rows only. `seal_up` and `board_height` are existing point-in-time fields already used by the V5 leader screens.

For one instrument, sorted by trading date:

- **启动 / launch:** current row is sealed and `board_height == 1`.
- **确认 / confirmation:** current row is sealed and `board_height == 2`.
- **发酵 / fermentation:** current row is sealed and `board_height == 3`.
- **加速 / acceleration:** current row is sealed and `board_height >= 4`.
- **分歧 / disagreement:** current row is not sealed; immediately previous row was sealed with `board_height >= 3`.
- **反包 / counter_wrap:** current row is sealed; immediately previous row was not sealed; row T-2 was sealed with `board_height >= 3`.
- **龙回头 / dragon_return:** current row is sealed after exactly 2 or 3 consecutive non-sealed rows, with the preceding row before that interruption sealed at `board_height >= 3`.

Recovery labels take precedence over ordinary board-height labels. For example, a reseal that mechanically has `board_height == 1` is labelled `counter_wrap` or `dragon_return`, not `launch`.

This precedence is part of the frozen representation and is not an outcome-dependent choice.

## What L01 measures

L01 reports only structural facts:

1. count, active dates and instruments for each proxy stage;
2. raw-flag overlap before precedence resolution;
3. immediate next-row and next-labelled-stage transition tables;
4. precursor-consistency rates, such as whether a `confirmation` row immediately follows `launch`, or a first `acceleration` row follows `fermentation`;
5. technical invariant failures, if any;
6. a parquet of stage annotations for reproducibility.

No forward-return columns are used for qualification and no trading performance metric is produced.

## Structural status

The only pass-like state is `STRUCTURALLY_VALID_FOR_DESCRIPTIVE_STAGE_AUDIT`. It means the frozen proxy is internally consistent on the persisted data. It **does not** mean the seven-stage theory predicts returns, and it does not authorize using the labels as signals.

`TECHNICALLY_INVALID` is returned if required fields are absent, date/instrument keys are duplicated, stage invariants fail, or the generated stage labels violate their frozen definitions.

There is deliberately no minimum-profit, win-rate, CAGR, Sharpe, threshold-search or promotion gate here.

## Prohibited actions

- do not tune board-height cutoffs after seeing transition frequencies;
- do not turn the best-looking stage into a strategy from this audit;
- do not use stage counts to rescue B01/B02/B03;
- do not retrofit these labels into X02;
- do not authorize paper or live trading;
- do not interpret `STRUCTURALLY_VALID` as economic validation.

A later experiment may study returns only after a separate preregistration names the stage(s), horizon, control, costs and statistical gate before outcomes are read.
