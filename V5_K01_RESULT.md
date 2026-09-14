# V5 K01 frozen result — book-grounded 20-day moving-average direction veto

## Outcome

Status: **NOT_VALIDATED**  
Validated as risk veto: **false**

K01 tested the supplied-book statement that stocks whose 20-day moving-average direction is downward should not be participated in. The preregistered operational translation used only the sign of the point-in-time 20-day moving-average slope: `MA20_T < MA20_T-1` versus non-downward `MA20_T >= MA20_T-1`. No slope threshold, rank, optimizer, price/volume/industry/regime/X02 filter, or moving-average-window search was allowed.

Entry was the next available open after signal close, the primary horizon was 2 trading days, and fixed round-trip cost was 0.36%. The comparison was same-date cross-sectional mean executable return, so broad market-day effects were paired rather than confused with the stock-level rule.

## Primary 2-day result

| segment | non-downward n | downward n | paired days | non-downward mean net | downward mean net | non-downward - downward paired diff | paired bootstrap 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2021-2023 development | 214,306 | 273,048 | 641 | -0.4060% | -0.3760% | -0.0159% | [-0.0981%, +0.0638%] |
| 2024+ historical-later | 224,446 | 236,835 | 645 | -0.2247% | -0.2859% | +0.0042% | [-0.1031%, +0.1084%] |

Mean market excess for the downward-MA20 control was -0.0044% in development and -0.0149% in historical-later. The later segment therefore had the expected sign direction, but the cross-sectional advantage was only +0.0042% and its bootstrap interval comfortably crossed zero. Development had the opposite paired direction.

The preregistered gate failed because:

- development non-downward-minus-downward 2-day paired difference was not positive;
- development paired bootstrap 95% lower bound was not above zero;
- historical-later paired bootstrap 95% lower bound was not above zero.

Coverage was very large in both periods, so this is not a small-sample failure.

## Interpretation boundary

This result rejects only the **isolated literal MA20-direction veto** under the frozen causal protocol. It does not imply that every trend-based rule in the books is false. The source itself places the 20-day-line rule inside a broader short/medium-term selection context together with chart order, bottom formation, main-rise stage, market environment, theme, sentiment and safety.

K01 may not be rescued by trying MA18/19/21/30/45, multi-day slope windows, slope thresholds, or by adding the best-looking historical filter after seeing this result. Any broader context rule must be separately sourced and preregistered as a new experiment. K01 cannot be retrofitted into X02, B01, B02 or B03, and it authorizes no portfolio, paper-trading or live-trading change.
