# V5 L02 frozen result — confirmation vs disagreement

## Outcome

**REJECTED**

L02 tested exactly the preregistered comparison committed before any L02 return was computed:

- selected: frozen L01 `confirmation` stage;
- control: frozen L01 `disagreement` stage;
- primary horizon: 2 trading days;
- entry: next available open, with a next-session upper-limit lock treated as unfilled;
- round-trip cost: 0.36%;
- development: 2021-05-17 through 2023-12-31;
- historical-later: 2024-01-01 through 2026-09-03;
- expected direction: `confirmation > disagreement`.

The primary contract was not changed after results appeared.

## Coverage

Across the full L02 research interval:

| cohort | signals | active dates | executable | executable active dates | fill rate |
|---|---:|---:|---:|---:|---:|
| confirmation | 779 | 390 | 736 | 373 | 94.48% |
| disagreement | 192 | 119 | 192 | 119 | 100.00% |

Both historical partitions passed the preregistered sample-coverage gates, so the negative conclusion is not an `INSUFFICIENT` result.

## Primary 2-day result

| metric | development 2021–2023 | historical-later 2024+ |
|---|---:|---:|
| confirmation executable n | 256 | 478 |
| confirmation active days | 179 | 192 |
| confirmation mean net return | **-1.7125%** | **-2.5149%** |
| confirmation median net return | -2.3608% | -4.1387% |
| confirmation win rate | 38.67% | 32.22% |
| confirmation mean market excess | **-1.5825%** | **+0.0199%** |
| disagreement executable n | 59 | 133 |
| disagreement active days | 51 | 68 |
| disagreement mean net return | -1.3742% | -4.4001% |
| paired dates | 20 | 29 |
| confirmation minus disagreement | +1.3571% | +0.5638% |
| paired bootstrap 95% CI | **[-3.8615%, +6.4306%]** | **[-2.3086%, +3.4642%]** |

The relative point estimate favored confirmation in both partitions, but that is not enough for the frozen gate. Confirmation's absolute 2-day return was negative in both periods; development market excess was negative; and neither paired bootstrap lower bound was above zero.

## Frozen gate failures

The preregistered gate failed for these reasons:

- development confirmation 2d mean net return was not positive;
- development confirmation 2d mean market excess was not positive;
- development paired 95% bootstrap lower bound was not above zero;
- historical-later confirmation 2d mean net return was not positive;
- historical-later paired 95% bootstrap lower bound was not above zero.

Therefore:

- `qualified_for_execution_validation = false`;
- `portfolio_combination_authorized = false`;
- `paper_trading_authorized = false`;
- `live_trading_authorized = false`.

## Interpretation

The supplied book's stage sequence can be represented coherently (L01), but the simple economic operationalization **"confirmation has positive and statistically superior next-open 2-day expectancy versus disagreement"** is not supported.

This does **not** prove that the book's broader stage framework is useless. It shows that this exact daily proxy, entry convention, cost assumption, horizon and stage pair failed the preregistered economic gate. The relative point estimate cannot be used to rescue the test because the bootstrap interval crosses zero and the selected cohort loses money in absolute terms.

No other stage pair may be substituted after seeing this result. Any future economic stage experiment requires a new source-grounded hypothesis and a new preregistration committed before its returns are read.

## Reproducibility

- PR: #18
- evaluated head SHA: `3ef80dddfb69ac53865cf1be4fa72c9623fc94a1`
- GitHub Actions run: `34810304552`
- unit tests: 8 passed
- full historical screen job: succeeded
- result artifact: `v5-l02-stage-economic-results`, artifact id `10334906156`
- uploaded artifact ZIP SHA-256: `9db718862a70b2d48c63ef4133f827d402800d951f87f17fac86c660078130ae`

This file records the one-shot outcome; it is not a new trading rule and does not authorize retuning L02.
