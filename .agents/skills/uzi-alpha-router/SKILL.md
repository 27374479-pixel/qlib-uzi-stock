---
name: uzi-alpha-router
description: 以严格样本外证据为门槛研究和筛选A股高超额收益机会；《48位游资》上下册、公开游资语录和外部A股实证研究只提供可证伪假说，不按人物投票。先判断市场/投机/题材/角色状态，再只启用已通过证据注册表的setup；未通过分钟执行验证的模块不得冒充可实盘alpha。
---

# UZI Alpha Router — evidence-gated research skill

## 目标

目标不是复刻任何游资，而是建立一个可淘汰、可组合、可更新的 A 股 alpha 系统：

`Regime -> Setup Family -> Role -> Candidate Rank -> Execution -> Risk`

《48位游资》上下册与公开语录是 **hypothesis provenance**，不是权威。人物不拥有投票权。任何观点只有通过本项目自己的 point-in-time、OOS、成本、成交和压力测试后，才能进入决策层。

## 证据文件优先级

每次研究前按顺序读取（存在时）：

1. `output/alpha_evidence_registry_v1.json`
2. `output/book_alpha_daily_screen_v3.json`
3. `output/attention_timing_decomposition_v1.json`
4. `output/external_challenger_daily_screen_v1.json`
5. 需要分钟执行时，再读取对应 fixed-signal minute validation 输出。

如果证据文件不存在或样本不足，本 skill 只能处于 `RESEARCH_ONLY`，不得把书本规则直接升级为 `PROBE`。

## 模块准入门槛

证据注册表中的 `promotion` 决定权限：

- `REJECTED / WEAK_NOT_ADMITTED`：禁止作为正向买入理由；可作为反证/风险提示。
- `INSUFFICIENT`：只允许继续采样，不允许交易化。
- `PROMISING_RETEST`：允许列为研究候选，不允许称为已验证 alpha。
- `DAILY_PASS`：日线状态/排序具有增量信息，但仍需确认是否存在可成交窗口。
- `MINUTE_VALIDATION_REQUIRED`：必须通过固定信号的 5m/1m 回放、T+1、涨跌停、成本和延迟测试后才能交易化。
- `EARLIER_ENTRY_REQUIRED`：日线看到的优势主要发生在下一开盘前；禁止用 T+1 开盘追入，必须寻找更早的盘中触发，否则只用于旧仓持有/退出。

最终实盘候选还必须有独立的 `MINUTE_PASS` 证据；没有这个状态时，本 skill 仍是研究系统。

## 四层状态，不先压成一个“情绪分数”

### 1. Market layer

观察市场广度、指数方向、跌停、波动和流动性。回答：大多数股票的风险预算应该增加还是减少？

### 2. Speculative layer

观察涨停/触板/炸板、昨日强股反馈、连板生态、重复高注意力拥挤。回答：短线资金是在赚钱、扩散，还是在兑现/杀高度？

### 3. Theme/Event layer

优先真实事件时间线与动态题材簇；CSRC 行业只能作弱代理。回答：这是新信息首次扩散、旧热点反复，还是分歧后的修复？

### 4. Stock role layer

角色必须有历史连续性：此前强势/成交地位、题材功能、相对强度、可交易性。单日涨幅第一、单次涨停、龙虎榜称谓都不能自动授予“龙头”。

只有四层组合对应一个已准入 setup 时才允许继续。

## 当前研究中的 setup families

下列名称只是模块槽位，是否启用必须读取 evidence registry：

- `NO_TRADE_WEAK`：弱市 veto / 风险路由。
- `PANIC_REPAIR`：集体恐慌后的共同修复，不做单股“跌多了”。
- `NEW_EVENT_PROBE`：真实新事件首次扩散的小规模试错；行业上涨不等于新事件。
- `BREADTH_WITH_LEADER`：核心与群体扩散同时成立。
- `POST_DIVERGENCE_REPAIR`：题材分歧后恢复。
- `DIVERGENCE_SURVIVOR`：分歧中的旧核心幸存者，不拿新跟风替代。
- `ROLE_PERSISTENCE`：历史角色持续，而非当日涨幅标签。
- `AMOUNT_ACCELERATION`：成交额增量仅作条件/排序，不机械越大越好。
- `TURNOVER_SWEET_SPOT`：检验倒U换手关系，不寻找神奇单点阈值。
- `HIGH_VOLUME_DIVERGENCE`：高量发生在分歧幸存阶段，而不是一致高潮追涨。
- `TREND_PULLBACK`：主升角色回踩，不等于下跌趋势低吸。
- `ATTENTION_SATURATION_VETO`：重复涨停/高注意力拥挤的反向 challenger。
- `LIMIT_ADJUSTED_MOMENTUM`：区分持续强势与由涨停过度反应堆出的原始动量。
- `LOTTERY_CROWDING_VETO`：低价+高波动+高换手+高涨停频率可能是拥挤彩票特征。
- `T1_DELAYED_REVERSAL`：研究 T+1 规则下高换手下跌后的可获得反转。
- `OVERNIGHT_INFORMATION`：研究 overnight return 是否比日内成分包含更多可持续信息。

## 明确降级/禁止的旧规则

除非未来新 OOS 推翻现有证据，否则：

- 不做“多个首板 -> 收盘确认核心 -> 次日开盘追”。
- 不把行业相对强度直接当作真实题材合力。
- 不因为已经涨停/高板而事后授予龙头身份并追入。
- “三板、低于10元、10亿成交额、某固定胜率”等书本数字不能单独触发交易。
- 不用低价、微盘、高波动制造出来的收益冒充可扩展 alpha。
- 不把 `T close -> T+1 open` 的收益算成 `T+1 open` 新仓可获得收益。

## 收益时段必须拆开

对强股/涨停/核心相关状态至少报告：

- `T close -> T+1 open`：隔夜溢价；对 T 收盘后才形成的信号不可由新仓获得。
- `T+1 open -> T+1 close`：日内变化，但新买 A 股仍受 T+1 不可卖限制。
- `T+1 close -> T+2 open`：第二隔夜风险。
- `T+1 open -> T+2 open`：次日开盘新仓最基本的可实现短周期结果。

如果正收益只存在第一段，模块应标为 `EARLIER_ENTRY_REQUIRED`，而不是宣称“次日追龙头有效”。

## 研究流程

1. **加载证据注册表**：先列允许、待分钟验证、弱/拒绝模块。
2. **冻结 asof**：记录北京时间、最后完成K线、事件 `knowledge_time`、数据源。
3. **判四层状态**：Market / Speculative / Theme / Role 分开给证据，不用一个综合分隐藏矛盾。
4. **选择唯一 setup family**：同一候选不能在失败后换名字解释。
5. **生成候选与 control**：每个正向条件都要说明对照组，防止把市场 beta 当 alpha。
6. **执行门槛**：下一根可交易K线；A股T+1；涨停锁死不买；跌停/停牌/滑点/成本真实处理。
7. **固定信号压力测试**：成本×2、延迟5/10/30分钟、去最佳5%、半年分段、development/OOS。
8. **更新 evidence registry**：新证据只能改变模块状态，不能事后修改原交易标签。

## OOS 与过拟合纪律

- 开发段和 OOS 分开；默认 2023+ 为当前重要 OOS，但未来继续向前滚动。
- 不在 OOS 上搜索阈值；宽分箱/阈值必须先注册。
- 必须同时报告绝对收益、同日市场超额、同类 control 差值。
- bootstrap 以交易日为主要重采样单位，避免同日多个信号假装独立样本。
- 删除最佳5%交易后仍需保持合理方向。
- 单一半年/单一妖股贡献过高自动降级。
- `PASS` 不是永久身份；新 OOS 可将其降级。

## 输出格式

```text
asof:
research_mode: RESEARCH_ONLY / EVIDENCE_GATED / MINUTE_VALIDATED
market_layer:
speculative_layer:
theme_layer:
role_layer:

active_module:
evidence_status:
why_enabled_or_disabled:

candidate:
  setup_family:
  signal_time:
  earliest_execution:
  executable_price_logic:
  invalidation:
  T1_risk:
  counterfactual_control:

expected_edge:
  absolute:
  date_neutral_excess:
  control_difference:
  sample_size:
  robustness:

now_action: NO_TRADE / WATCH / PROBE / ADD / HOLD / REDUCE / EXIT
```

在未完成分钟执行验证前，`PROBE/ADD` 只能用于已经明确标记 `MINUTE_PASS` 的模块；否则输出 `WATCH` 或 `NO_TRADE`。

## 最终原则

**我们不需要证明书是对的，也不需要证明某位游资是对的。只需要找到在今天仍能用、可成交、样本外稳定、能承受成本与延迟的机制。**
