# V5 B01 preregistration — leader first-disagreement with real participation

Status: FROZEN BEFORE FIRST B01 RESULT.

This experiment is derived from the two user-supplied `48位游资` books. It is a falsification screen, not a parameter search and not a portfolio authorization.

## 1. Source claims

The upper-volume leader section groups the following observations together:

- leaders often become identifiable around a three-board launch;
- the first meaningful disagreement is accompanied by unusually large / historically high volume;
- repeated board-by-board turnover matters because the position remains accessible rather than becoming an inaccessible one-word acceleration;
- the book gives `10亿元+` as a disagreement-turnover heuristic;
- leaders may start before an index adjustment has completely ended.

The upper volume also explicitly discusses the `leader first-negative-day / leader return / second-wave` family. The lower volume repeatedly treats market cycle and prevailing trend as conditioning variables rather than reasons to force a trade in every environment.

B01 translates only the directly observable parts into a fixed daily precursor. Market regime is diagnostic only in this first experiment; it is not allowed to change eligibility after results are seen.

## 2. Causal timing and universe

- Universe: point-in-time CSI800 using the repository's existing membership, ST, listing-age, trading-status and price-limit policy.
- Signal timestamp: completed daily close on signal date `t`.
- Entry proxy: next available trading-session open `t+1`; if the next session is locked at the upper limit and never trades below it, the order is unfilled.
- Primary exit: open after two additional trading sessions (`2d` label in the existing screen convention).
- Descriptive exits: `1d` and `5d` only. They do not determine B01 qualification.
- Round-trip cost: fixed `0.36%`.
- Historical partitions: `2021-05-17 .. 2023-12-31` development and `2024-01-01 .. data end` historical-later.
- Bootstrap: 5,000 resamples by signal date, fixed seed `20260914`.

## 3. Fixed event definition

### 3.1 Leader precursor

A stock is in the B01 leader precursor set on signal date `t` only when the immediately preceding trading row was a sealed board with `board_height >= 3`.

This directly encodes the book's three-board leader-launch observation. No future board height or ex-post leader label is used.

### 3.2 First disagreement

`first_disagreement(t)` is true when:

- the immediately preceding row satisfies the leader precursor above; and
- the current row is **not** sealed at the upper limit.

Because the preceding row is still part of the consecutive sealed streak, the first non-sealed row is mechanically the first daily break in that streak. No future recovery is used.

### 3.3 Book-grounded participation package

The primary selected cohort must satisfy all of the following on the disagreement day:

1. `amount >= prior_20_session_amount_max`, where the 20-session maximum excludes the current row;
2. `amount >= 1_000_000_000 CNY` (the book's explicit 10亿元 heuristic);
3. none of the preceding three sealed-board rows was a one-word board (`prior3_one_word_sum == 0`).

This is named `high_participation_first_disagreement`.

No percentile, optimized multiplier, volatility threshold, return threshold, market-breadth threshold or discretionary chart pattern is allowed in the primary selector.

## 4. Frozen controls

The primary matched control isolates the historical-high-volume clause while holding the other source conditions fixed:

`volume_control`:

- same first-disagreement event;
- `amount >= 1_000_000_000 CNY`;
- `prior3_one_word_sum == 0`;
- valid prior 20-session amount maximum exists;
- **current amount < prior_20_session_amount_max**.

Two secondary diagnostic controls are reported but do not decide B01 qualification:

- `accessibility_control`: same event, current amount is a prior-20-session high and >=1bn, but at least one of the preceding three boards was one-word;
- `turnover_size_control`: same event and accessible three-board path with current amount a prior-20-session high, but current amount <1bn.

If any diagnostic control has too few observations, it is reported as insufficient; its absence must not be converted into a pass.

## 5. Primary horizon and qualification gate

The primary horizon is **2 trading days after next-open entry**, matching the short holding-period emphasis in the supplied short-term trading material. `1d` and `5d` are descriptive.

B01 is `QUALIFIED_FOR_MINUTE_REPLAY` only if **all** conditions below hold in both development and historical-later partitions:

- selected executable observations >= 30;
- selected active signal dates >= 20;
- selected 2d mean net return > 0;
- selected 2d mean same-date market excess > 0;
- selected-vs-`volume_control` paired days >= 15;
- selected-vs-control expected signed 2d difference > 0;
- lower bound of the date-bootstrap 95% CI for the paired difference > 0.

Otherwise status is `REJECTED` (or `INSUFFICIENT` when the explicit sample minima are not met). A failure is frozen and does not authorize changing 3 boards, 20 sessions, 1bn, the holding period, cost or sample thresholds.

## 6. Mandatory diagnostics

The report must include, without changing the gate:

- 1d / 2d / 5d selected and primary-control metrics;
- both secondary control comparisons where sample exists;
- signal counts and fill rate;
- weak-market versus non-weak-market 2d selected metrics;
- yearly selected 2d metrics;
- best-5%-trimmed market excess and half-year concentration from the shared screen metrics.

The regime split is attribution only. It must not be turned into a router threshold from this same result.

## 7. Research boundary

A B01 pass permits only a separately preregistered minute-level replay of the same frozen signal family. It does not authorize:

- combining B01 with X02;
- changing B01 thresholds;
- a live trading rule;
- calling the system all-weather.

A B01 failure remains useful evidence about which book claim did not survive a causal executable test.