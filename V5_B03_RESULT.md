# V5 B03 frozen result — leader second-wave restart

## Outcome

Status: **INSUFFICIENT**  
Qualified for minute replay: **false**

The frozen B03 selector was a point-in-time market-max sealed leader, followed by exactly 2 or 3 consecutive non-sealed sessions, followed by the first reseal. The primary control used the same 2/3-session interruption and reseal structure after a lower-than-market-max prior sealed streak. Entry was the next available open, primary horizon 2 trading days, fixed round-trip cost 0.36%.

## Primary 2-day result

| segment | selected n | active days | mean net return | mean market excess | paired days | selected - control | paired bootstrap 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2021-2023 development | 93 | 79 | -1.2644% | -1.0703% | 9 | +2.7351% | [+0.2037%, +5.6515%] |
| 2024+ historical-later | 89 | 70 | -1.5284% | -0.2869% | 14 | -0.2656% | [-4.4491%, +4.5227%] |

Overall counts before horizon completeness: selected 187 signals on 153 active dates, 183 executable; lower-height control 197 signals on 127 active dates, 194 executable.

The preregistered gate required at least 15 same-date pairs in each segment; observed paired-date counts were only 9 and 14. More importantly, selected absolute 2-day net return and mean market excess were negative in both historical segments, and the 2024+ relative comparison was also negative. Therefore B03 does not qualify for minute replay even apart from the paired-date coverage shortfall.

## Diagnostics are not new hypotheses

The preregistration allowed separate descriptions of 2-session and 3-session interruptions but explicitly prohibited promoting the better-looking diagnostic after observing outcomes. For example, the 3-session development subset had a small positive mean return/excess while the 2024+ 3-session subset still had negative absolute mean return. That observation **must not** be used to rewrite B03 into a 3-session-only rule.

## Interpretation

This result does not say that every discretionary `龙二波` or `龙回头` implementation is false. It says that this preregistered, causal daily proxy — market-max leader, 2/3-day non-sealed interruption, then first reseal and next-open entry — did not earn promotion. Any different confirmation, timing or replacement-leader concept must come from a separately sourced and preregistered experiment rather than from B03 result mining.
