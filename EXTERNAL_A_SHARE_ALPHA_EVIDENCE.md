# A股外部实证证据：对《48位游资》假说的 challenger 清单

目的不是用论文替代短线交易，而是用独立大样本证据挑战书中经验。书本观点与外部证据一致时提高研究优先级；冲突时必须设计对照实验，不能因为“名人语录”保留规则。

## 1. 涨停/注意力不是无条件正 alpha

### Cai, Jiang & Liu (2022), International Review of Financial Analysis
**Investor attention, aggregate limit-hits, and stock returns**，DOI: 10.1016/j.irfa.2022.102265。

- 2002–2017 A股。
- 月内涨跌停触及次数作为注意力代理。
- 高频触及股票未来横截面收益更低；高 UP 组合形成月很强，但随后月份出现显著反转。
- 作者把机制归因于注意力驱动的散户净买压。

**对项目的挑战**：`prior_touch20/prior_seal` 不能只加分。重复触及更可能表示 attention saturation。需要测试“首次/低频注意力”与“重复注意力”分层。

### Chen et al. (2019), Journal of Econometrics
**Daily price limits and destructive market behavior**，DOI: 10.1016/j.jeconom.2018.09.014。

- 使用深交所账户级数据。
- 大投资者在触及涨停当日买入、次日卖出；涨停日更强净买入与更强长期反转相关。

**对项目的挑战**：如果信号直到涨停收盘才生成，T+1 开盘新买可能位于更早资金的退出窗口。涨停角色更适合作为“已持仓的隔夜/退出状态”或盘中预先识别条件，而非次日追入理由。

### Wang et al. (2015), PLOS ONE
**Statistical Properties and Pre-Hit Dynamics of Price Limit Hits in the Chinese Stock Markets**，DOI: 10.1371/journal.pone.0120312。

- 2000–2011 全A股高频数据。
- 涨停收盘后，次日开盘继续向上的概率很高；但文中也显示效应依赖市值、牛熊状态与触及时间。

**对项目的启示**：必须拆分 `T close -> T+1 open`（隔夜）和 `T+1 open -> later`（可供次日新买者获得）。不能用 close-to-next-open 的溢价证明 T+1 开盘买入有效。

### Hu (2026), Applied Economics Letters
**Upper price limit, lottery preference, and cross-section of stock returns**，DOI: 10.1080/13504851.2026.2613078。

- 高频上限触及可作为中国市场彩票偏好代理。
- 高 UPL 频率股票未来显著跑输低 UPL 频率股票，并且不能被传统 lottery 特征完全解释。

**对项目的启示**：`低价 + 高频涨停 + 高波动` 更应首先作为拥挤/彩票特征的负向 challenger，而不是“妖股潜力”正向分数。

## 2. 原始动量在A股可能被涨停过度反应污染

### Price overreaction to up-limit events and revised momentum strategies (Economic Modelling, 2022)
DOI: 10.1016/j.econmod.2022.105910。

- 2000–2020 A股。
- 研究认为涨停事件存在价格过度反应，污染普通动量形成期；剔除这部分过度反应后，中期动量重新显著。

**新假说**：比较 `raw_momentum` 与 `limit-adjusted momentum`。如果一只股票 20/60 日涨幅主要由数个涨停日贡献，其后续期望可能低于“没有极端涨停、但持续相对强”的股票。

## 3. A股更需要区分动量与反转的时间尺度

### Chui, Subrahmanyam & Titman (2022), Review of Finance
**Momentum, Reversals, and Investor Clientele**，DOI: 10.1093/rof/rfac010。

- A/B股投资者结构提供自然实验。
- A股更明显表现出反转，而机构占比更高的 B 股更容易表现动量。

**对项目的启示**：不能用一个“强者恒强”分数覆盖所有持有期。1–2日、5日、20日必须独立报告；router 需要决定当前是 momentum continuation 还是 attention/reversal regime。

## 4. 彩票/低价不能脱离隔夜风险

### Gu, Hu & Xiong (2025), Accounting & Finance
**Dissecting the lottery-like anomaly: Evidence from China**，DOI: 10.1111/acfi.13354。

- 中国 A 股的彩票型异常主要由隔夜收益部分驱动。
- 彩票偏好和套利限制会加强该效应。

**对项目的启示**：书中“低于10元、炒作空间大”必须做 placebo/control。价格低本身不能晋级；还必须分解 overnight 与 intraday/post-open 回报，防止把不可获得的隔夜成分算成新入场 alpha。

## 5. 注意力在不同层级可能方向不同

### Retail Investor Attention and Stock Returns (2026)
- 市场、行业、个股注意力与当日收益正相关；行业和个股注意力在更长窗口出现反转，而市场层注意力更持久。

### Lin et al. (2023), Journal of Banking & Finance
**Cranes among chickens: The general-attention-grabbing effect of daily price limits in China's stock market**，DOI: 10.1016/j.jbankfin.2023.106818。

- 对涨跌停注意力暴露更高的股票未来收益更低，散户持有更重时更明显。

**对项目的启示**：涅槃重升式“市场情绪 / 板块情绪 / 个股投机情绪”分层是有研究价值的。市场层强不等于某只极端高注意力个股仍有正 alpha。

## 新增 challenger 假说

### X01 attention saturation
在相同角色/题材状态下，过去20日仅1–2次涨停触及的核心是否优于4次以上的高注意力核心？

### X02 limit-adjusted momentum
构造过去20/60日收益时，将涨停/触板日收益从形成期剔除或单列。测试“平滑持续强势”是否优于“极端涨停堆出的强势”。

### X03 alpha timing migration
对每类事件同时报告：
- `T close -> T+1 open` overnight gap；
- `T+1 open -> T+2 open` post-entry return；
- `T+1 open -> T+1 close`（有可靠日内/收盘时）；
- `T+1 close -> T+2 open`。

如果收益只发生在 T+1 open 之前，则该状态不能作为 T+1 新仓 alpha，只能用于 T 日已有持仓管理或要求更早的分钟触发。

### X04 lottery crowding veto
`低价 + 高频涨停 + 高波动 + 高换手` 作为拥挤彩票因子。测试其是否应当从候选分数中扣分，而非加分。

### X05 emotion-layer interaction
把市场广度/指数状态、投机生态（涨停/连板/炸板）、题材扩散、个股注意力分开，不提前合成一个情绪分数。测试四层交互后再决定哪个 setup 可启用。

## 研究纪律

外部论文只提供 challenger，不直接写成交易规则。任何新增因子仍必须通过本项目自己的点时数据、T+1、成本、OOS、去最佳交易、半年分段与分钟执行验证。
