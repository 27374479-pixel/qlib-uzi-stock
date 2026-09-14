# V5 L02 — preregistered leader-stage economic comparison

## Research question

Does the already-frozen L01 **confirmation** stage have better short-horizon executable expectancy than the already-frozen L01 **disagreement** stage?

This question is frozen **before any L02 forward-return result is computed or inspected**.

## Source basis

Primary source: user-supplied `48位游资-下册`, PDF page 123/227 (printed p.92).

The page lists the leader evolution:

`启动 -> 确认 -> 发酵 -> 加速 -> 分歧 -> 反包 -> 龙回头`

Its explanatory text characterizes the earlier progression as continued growth / increasing recognition, while the disagreement stage is the point at which buyers and sellers no longer share one view. L02 treats that wording as support for one narrow directional comparison only:

**confirmation should have higher two-trading-day forward expectancy than disagreement.**

This is an operational research hypothesis, not a verbatim promise from the book.

## Frozen representation dependency

L02 must use the exact L01 proxy definitions from `V5_L01_LEADER_STAGE_PROXY_SPEC.md` and `v5_l01_leader_stage_transition_audit.py`.

Selected cohort:

- `stage_proxy == confirmation`;
- mechanically: current completed daily row is sealed and `board_height == 2`, subject to the frozen L01 precedence rules.

Primary control cohort:

- `stage_proxy == disagreement`;
- mechanically: current completed daily row is not sealed, immediately previous row was sealed with `board_height >= 3`, subject to the frozen L01 precedence rules.

L02 is not allowed to change the L01 board-height definitions or label precedence after seeing returns.

## Why this pair was chosen before outcomes

The choice is based on **source semantics and pre-return structural coverage**, not on economic results.

The L01 structural audit produced enough representation coverage for confirmation and disagreement to support a falsifiable comparison, while later recovery states such as counter-wrap and dragon-return are much sparser. Sparse recovery stages are therefore not used as the L02 primary endpoint.

No acceleration-vs-disagreement, fermentation-vs-disagreement, counter-wrap or dragon-return result may replace the primary comparison after the fact.

## Frozen data and timing

- Universe: point-in-time CSI800 membership used by the existing V5 daily screens.
- Start: `2021-05-17`.
- End: `2026-09-03`.
- Development partition: `2021-05-17` through `2023-12-31`.
- Historical-later partition: `2024-01-01` through `2026-09-03`.
- Signal information: completed daily row only.
- Entry: next available trading row open.
- Locked-limit handling: if the next session never trades below its upper limit under the repository's existing daily fill rule, the signal is unfilled.
- Primary horizon: **2 trading days**, using the existing repository label convention `entry T+1 open -> T+3 open`.
- Diagnostic horizons: 1 and 5 trading days only; they cannot change the primary verdict.
- Round-trip cost: **0.0036** (36 bps), identical to the conservative B01 daily screen.
- Bootstrap samples: **5000**.
- Seed: **20260914**.

## Frozen primary metrics

For each partition, L02 evaluates:

1. confirmation cohort executable **2d mean net return**;
2. confirmation cohort **2d mean market excess**, where the baseline is the same-date eligible-universe executable return used by the existing daily screen;
3. same-date paired **confirmation minus disagreement** 2d return difference;
4. date-bootstrap 95% confidence interval for that paired difference.

The expected direction is positive: `confirmation > disagreement`.

## Frozen sample gates

Each partition must contain at least:

- 50 executable confirmation observations;
- 30 active confirmation signal dates;
- 30 executable disagreement observations;
- 20 active disagreement signal dates;
- 20 dates on which executable confirmation and disagreement observations are both present for the paired comparison.

If any sample gate fails, the result is `INSUFFICIENT`. No threshold may be relaxed after results are seen.

## Frozen qualification gate

L02 is `QUALIFIED_FOR_EXECUTION_VALIDATION_ONLY` only if **all** of the following hold in both development and historical-later partitions:

- all frozen sample gates pass;
- confirmation 2d mean net return is strictly positive;
- confirmation 2d mean market excess is strictly positive;
- same-date paired confirmation-minus-disagreement 2d difference is strictly positive;
- the paired date-bootstrap 95% lower bound is strictly above zero.

If sample coverage is sufficient but any economic condition fails, status is `REJECTED`.

There is no `PROMISING` escape hatch for the primary gate.

## Diagnostics that cannot rescue the primary result

L02 may report, for context only:

- 1d and 5d results;
- yearly or half-year stability;
- weak-market versus non-weak-market slices;
- fill rates;
- individual cohort bootstrap intervals.

A favorable diagnostic cannot rescue a failed primary gate. An unfavorable diagnostic does not override a primary pass unless it reveals a technical/data-integrity error.

## Prohibited actions

- no stage-pair search;
- no board-height retuning;
- no cost retuning;
- no horizon search;
- no changing the development/later split;
- no dropping bad dates or bad years;
- no using U03/B01/B02/B03/K01 outcomes to alter this contract;
- no X02 retuning;
- no portfolio combination based on L02;
- no paper or live trading authorization from L02.

A primary pass authorizes only a **separately specified execution validation**. A failure is frozen negative evidence for this exact operational hypothesis.
