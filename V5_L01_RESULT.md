# V5 L01 frozen result — book-grounded leader-stage representation audit

## Outcome

Status: **STRUCTURALLY_VALID_FOR_DESCRIPTIVE_STAGE_AUDIT**  
Alpha evaluation authorized: **false**  
Trading signal authorized: **false**

L01 did not test returns. It tested whether the supplied-book sequence `启动 -> 确认 -> 发酵 -> 加速 -> 分歧 -> 反包 -> 龙回头` can be represented by one frozen point-in-time daily proxy without technical contradictions.

The proxy and precedence were fixed before the persisted-data run. Recovery labels (`dragon_return`, then `counter_wrap`) override ordinary board-height labels so a reseal that mechanically resets to first-board status is not silently reclassified as a new `launch`.

## Coverage

Persisted CSI800 point-in-time data from **2021-05-17 through 2026-09-03** produced:

- 956,559 instrument-date rows;
- 7,116 labelled stage rows;
- 1,085 instruments;
- 1,289 active dates.

| proxy stage | rows | active dates | instruments |
|---|---:|---:|---:|
| launch | 5,765 | 1,115 | 900 |
| confirmation | 779 | 390 | 445 |
| fermentation | 192 | 123 | 149 |
| acceleration | 138 | 90 | 63 |
| disagreement | 192 | 119 | 149 |
| counter-wrap | 23 | 19 | 22 |
| dragon-return | 27 | 26 | 27 |

The late recovery states are therefore sparse relative to launch/confirmation. This is a descriptive coverage fact, not a reason to loosen their definitions.

## Structural consistency

All frozen label-definition invariants passed with **zero violations**, including recovery-label precedence.

Immediate precursor consistency was:

| check | matched / total | rate |
|---|---:|---:|
| confirmation immediately after launch | 766 / 779 | 98.33% |
| fermentation immediately after confirmation | 192 / 192 | 100% |
| first acceleration immediately after fermentation | 69 / 69 | 100% |
| later acceleration immediately after acceleration | 69 / 69 | 100% |
| disagreement immediately after high-board stage | 192 / 192 | 100% |
| counter-wrap immediately after disagreement | 23 / 23 | 100% |
| dragon-return with frozen 2/3-session interruption | 27 / 27 | 100% |

The 13 confirmation rows without an immediately visible `launch` are retained as observed boundary/history effects rather than repaired by inventing missing earlier states.

## What this does and does not establish

The audit establishes that this **operational proxy is technically coherent enough for descriptive stage research** on the persisted data. It does not establish that the book's stage theory predicts returns, that one stage is buyable, or that the seven labels are a unique/correct interpretation of discretionary trader language.

No forward-return field, entry rule, exit rule, CAGR, Sharpe, win-rate optimization or portfolio test was used to grant the structural status.

A future economic test must be a separate preregistered experiment. It must choose the stage(s), comparison group, horizon, costs and statistical gate before any stage-return outcome is read. L01 itself authorizes no changes to X02, B01/B02/B03, portfolio construction, paper trading or live trading.
