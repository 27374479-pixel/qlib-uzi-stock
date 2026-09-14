# V5 U04 result — book-grounded <10 CNY launch-price modifier

## Frozen outcome

**Status: `INSUFFICIENT`.**

The preregistered `<10 CNY` launch-price modifier did **not** qualify for promotion. This is not a threshold-tuning invitation: the exact 10-CNY boundary, three-board context, launch-price proxy, 2-day horizon and 36 bps cost remain frozen.

## Why the gate stopped

The one-shot historical screen did not meet the preregistered coverage requirements.

Across the full research interval, the frozen cohorts contained:

- `<10 CNY`: 50 signals, 38 active dates, 48 executable observations, 37 executable active dates, 96.0% fill rate;
- `>=10 CNY`: 71 signals, 45 active dates, 69 executable observations, 43 executable active dates, 97.18% fill rate.

But the gate is evaluated separately in the two frozen historical partitions.

### Development: 2021-05-17 .. 2023-12-31

- selected `<10`: 17 executable observations on 17 active dates;
- control `>=10`: 17 executable observations on 17 active dates;
- same-date paired comparison: only **2** dates.

All three counts miss the preregistered minimums (30 observations, 20 active dates, 15 paired dates).

Descriptively, the selected cohort's 2-day mean net return was **-1.0332%**, versus **-0.8794%** for the control. On the only two paired dates, selected-minus-control was **-8.2054%**. A bootstrap interval is intentionally unavailable because paired coverage is too small.

### Historical-later: 2024-01-01 .. 2026-09-03

- selected `<10`: 31 executable observations on 20 active dates;
- control `>=10`: 52 executable observations on 26 active dates;
- same-date paired comparison: only **5** dates.

The selected/control observation and active-date gates are met here, but the paired-date minimum of 15 is not.

Descriptively, selected 2-day mean net return was **-4.8290%**, versus **-6.2093%** for control. The five paired dates had a selected-minus-control point estimate of **+1.9468%**, but paired coverage is far below the frozen minimum and no valid bootstrap lower bound is available.

## Interpretation

The correct conclusion is **insufficient evidence**, not a pass and not a clean rejection of the source statement. The historical-later relative point estimate is positive, but it is based on only five paired dates and therefore cannot be promoted. The development paired point estimate is negative and is based on only two paired dates.

The experiment was intentionally framed as a **relative modifier** test. Even if it had passed, it would not have authorized a standalone signal. Because it did not pass the frozen gate, `qualified_as_relative_modifier_only=false`.

The result remains non-promoted. More future observations may eventually motivate a separately preregistered prospective study, but U04's frozen historical contract and outcome are not rewritten retroactively.

## Prohibited follow-up rescue

Do not use this result to:

- move 10 CNY to 8/12/15 CNY or a price quantile;
- redefine launch price after seeing the result;
- change three boards to two/four boards;
- remove the accessibility constraint to create more samples;
- change the 2-day horizon or 36 bps cost;
- select a favorable year, market regime, industry or theme;
- combine U04 with X02 or another sleeve to hide insufficient evidence.

A later experiment may revisit a distinct source-grounded claim, but U04 itself remains frozen.

## Technical record

GitHub Actions run `34811169668` completed successfully. Unit tests: **9 passed**. The full persisted point-in-time screen also completed successfully and uploaded artifact `v5-u04-launch-price-modifier-results` (artifact id `10334722998`; uploaded ZIP SHA-256 `971e23fabf483ac90f536cae71092267ce20ae7c706f8a1a099d884bcb11f082`).

No X02 retuning, portfolio combination, paper trading, or live trading is authorized by U04.
