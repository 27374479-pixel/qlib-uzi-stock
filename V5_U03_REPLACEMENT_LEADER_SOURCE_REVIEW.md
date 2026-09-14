# V5 U03 — replacement-leader / follower source review

## Decision

**DEFER_SIGNAL_PREREGISTRATION**

The supplied upper-volume OCR contains useful replacement-leader language, but the page is a multi-column layout whose text has been interleaved row-by-row during extraction. That makes several nearby claims individually readable while making their exact column-to-column relationship unreliable. U03 therefore records what is safe to carry forward and explicitly blocks a mechanical trading rule until the missing source definitions are resolved.

## Source fragments we can use safely

From the upper-volume text around the market-total-leader discussion:

- the page contains the phrase **`总龙头退潮两三天`**;
- it separately says some **跟风股 can evolve into 补涨龙**;
- it says a 补涨龙 can acquire strong **一致性 / recognition** once broadly accepted;
- nearby columns also discuss a market without a true leader, attempts to start a **竞争龙头**, a leader having a **左右手**, and main-hotspot / sentiment-resonance contexts.

The page also separately states that the market total leader can use named tactics such as first-yin, dragon-return and second-wave. Those tactics were already handled by B02/B03/L01 and must not be mixed into U03 after the fact.

## Why the OCR cannot support one mechanical rule yet

The extracted lines interleave several visually adjacent columns. For example, the same text rows contain phrases about `总龙头退潮两三天`, `市场震荡混沌期`, sudden news, competing leaders, a left/right-hand companion, followers becoming replacement leaders and high-board leaders. We cannot safely infer that all of those phrases form one causal sentence or one checklist.

Therefore U03 refuses to manufacture links such as:

- `leader ebbs for 2/3 days -> buy the strongest follower`;
- `market has no leader -> buy the first competing leader`;
- `leader has a left/right hand -> rank by board height`;
- `consensus -> require N limit-ups or X turnover`;
- `replacement leader -> must share the same industry/theme`;
- `buy on the first seal / next open / first break-out`.

None of those exact mechanical translations is established by the current source extract.

## Source-readiness fields

The following distinctions are frozen before any U03 outcome is produced:

| field | ready? | reason |
|---|---|---|
| leader-ebb rough window | yes | `两三天` is explicit, but only as contextual wording |
| target security identity | no | the source does not machine-define which follower / replacement candidate is the target |
| relationship to original leader/theme | no | nearby wording is interleaved; exact relationship is not safely recoverable |
| recognition / consensus observable | no | source gives the concept but no numeric market observable |
| candidate ranking rule | no | no defensible source rank is specified |
| entry timing | no | no safe source-grounded daily/minute entry rule is established here |
| exit/horizon | no | no U03-specific exit rule is established here |
| expected economic direction versus a control | no | becoming a replacement leader is descriptive; a return-superiority claim/control is not machine-specified |
| source layout integrity for this passage | no | OCR is multi-column and interleaved |

## What is allowed now

- preserve `总龙头退潮两三天` and `跟风 -> 补涨龙` as source evidence;
- search for a cleaner copy/page/image or another passage that defines the relationship more clearly;
- perform non-economic source/representation work only;
- keep the R01 router fail-closed while the market/opportunity and replacement-leader definitions remain unresolved.

## What is prohibited

- no U03 return screen;
- no parameter search over 1/2/3/4-day leader-ebb windows;
- no post-hoc reuse of B03 diagnostics;
- no arbitrary follower rank, theme filter, turnover threshold or entry time;
- no paper/live trading authorization;
- no claim that the current OCR proves one combined replacement-leader algorithm.

The correct next event for U03 is **better source evidence**, not a backtest.
