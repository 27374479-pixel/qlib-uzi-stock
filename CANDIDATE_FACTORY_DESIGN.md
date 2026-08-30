# UZI 前置候选工厂 V1

## 目标

候选工厂只解决“哪些股票值得花 UZI 的研究预算”，不输出买卖建议。它优先保证潜在赢家不被单一模型漏掉，再通过数据质量门减少明显假增长和不可交易标的。

## 流程

1. 一个或多个量化来源各保留固定配额，合并而不强求交集。
2. 在点时字段覆盖足够时，启用业绩拐点、周期反转、质量回调和产业催化四个证据池。
3. 财务红旗和可交易性问题是硬否决；缺失字段只降低置信度或停用对应证据池，不填零。
4. 合并来源形成研究优先级，但该分数仅用于分配研究预算。
5. 输出 UZI Lite、Medium、Deep 三层队列。Deep 必须同时具备较高数据置信度和至少一个非量化证据池。

## 输入契约

量化来源使用现有候选 JSON：

```powershell
.\.venv\Scripts\python.exe candidate_factory.py `
  --source qlib=output\base_candidates_20260703.json
```

多个来源可以并列输入：

```powershell
.\.venv\Scripts\python.exe candidate_factory.py `
  --source qlib=output\qlib_candidates.json `
  --source sequoia=output\sequoia_candidates.json `
  --features data_lake\curated\candidate_features\20260717.parquet
```

`--features` 必须是一行一股票的精确日期快照。核心字段分组如下：

| 分组 | 字段 |
|---|---|
| 可交易性 | `close`, `amount_20`, `trade_status`, `is_st` |
| 业绩拐点 | `revenue_growth_yoy`, `profit_growth_yoy`, `cashflow_to_profit`, `nonrecurring_profit_share`, `pe_ttm` |
| 周期反转 | `gross_margin_qoq_delta`, `capacity_utilization_qoq_delta`, `product_price_change`, `inventory_growth_delta`, `pb_mrq` |
| 质量回调 | `roe_ttm`, `debt_ratio`, `drawdown_120`, `pe_quantile_5y` |
| 产业催化 | `catalyst_score`, `earnings_revision_3m`, `relative_strength_60`, `ret20`, `dist_ma20` |

所有增长率和比率使用小数，例如 30% 写为 `0.30`。`cashflow_to_profit` 应使用 TTM 或最近两个季度合计口径，避免单季度季节性误杀。任何季度财务字段必须带公告日知识边界，由上游数据构建器保证在信号日已经公开。

## V1 安全约束

- 非经常损益占比超过 30%：硬否决。
- 经营现金流/净利润低于 0.5：硬否决。
- 应收或存货增速高于收入 20 个百分点：硬否决。
- ST、停牌、股价低于 2 元、20 日平均成交额低于 5000 万元：硬否决。
- 一个证据池的必需字段在全截面覆盖不足 20%：整个池停用，并在输出中记录原因。
- UZI Deep 不接受“只有单一量化来源、没有财务或催化证据”的候选。

## 验证计划

候选层评价未来 60 日赢家的 Recall@K；UZI 层评价 Precision@5、Precision@10、最大不利波动和否决后表现。必须同时保存候选工厂单独结果和 UZI 处理后的结果。从每周冻结快照开始建立影子组合，历史上无法还原的 UZI 定性信息不做伪回测。

## 下一阶段

1. 建设公告日对齐的季度财务快照。
2. 将公告、业绩说明会和订单事件标准化为可追溯的催化剂表。
3. 为每个候选保存最终入选原因、原始字段、UZI结论和未来收益标签。
4. 增加候选层 walk-forward 评估，比较单来源、并集、多来源投票和 UZI 否决。
