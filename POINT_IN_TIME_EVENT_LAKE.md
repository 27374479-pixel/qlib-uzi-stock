# Point-in-Time Event Lake (V4.17)

目标：为书本 H04「新题材首次扩散」和 H05「核心带动题材扩散」提供可回放、可追溯、无未来函数的历史事件数据。

## 第一阶段：历史公告

主源：AKShare `stock_notice_report`（东方财富公告大全）。

落盘：`data_lake/raw/eastmoney/notices/YYYY/MM.parquet`

Manifest：`data_lake/manifests/eastmoney_notices_YYYYMMDD_YYYYMMDD.json`

### 字段

- `event_id`：稳定 SHA256 派生 ID；优先使用源公告 `AN...` 编号。
- `source_event_id`：源公告编号（若 URL 可解析）。
- `provider` / `source_endpoint` / `schema_version`：数据血缘。
- `security_code`：源证券代码。
- `instrument`：可保守识别时映射成 `SH/SZ/BJ`；债券等保持空。
- `security_type_inferred`：`equity` 或 `unknown`。
- `event_type`：源公告类型。
- `title`：公告标题。
- `source_url`：原始公告链接。
- `published_date`：供应商给出的公告日期。
- `eligible_from_date`：最早允许进入回测的日期。
- `event_time_precision`：当前为 `date`。
- `knowledge_policy`：当前固定 `published_date_plus_1_calendar_day`。
- `query_date`：历史接口查询日期。
- `collected_at_utc`：本次采集时间，仅代表 ingestion time，不冒充历史 first_seen。

## 因果规则

历史接口只有公告“日期”，没有可靠的盘中发布时间。因此：

> 公告日 D 的事件，最早从 D+1 日开始允许进入任何信号或题材聚类。

这是一条保守规则。即使公告实际在 D 日盘前发布，也不允许回测在 D 日使用；宁可损失信息时效，也不制造未来函数。

周末和节假日无需额外向后填充：`eligible_from_date=D+1 calendar day`，实际研究面板与交易日连接后会自然落到下一交易日。

## 禁止事项

1. 不把 `collected_at_utc` 当历史发布时间。
2. 不使用今天的概念成分股回填 2021–2026。
3. 不根据事后股价表现给公告贴“热点/主线”标签。
4. 不把静态 `industry_code` 冒充动态题材。
5. H04/H05 只有在事件聚类本身可 point-in-time 构造后才允许回测。

## 下一阶段

公告层通过完整性校验后，再构造：

1. `event_cluster_id`：只依据当时可见标题/正文建立的事件簇；
2. `first_seen_date`：事件簇第一次可知日期；
3. `event_stock_membership`：当时已由公告/新闻直接关联到的股票，不使用未来概念成员；
4. H04：新事件出现后是否形成跨股票扩散；
5. H05：已形成核心的事件簇是否出现群体扩散和持续反馈。

公告标题只能作为第一阶段事件载体；若后续需要正文，必须单独保存原始文本及其 source timestamp/knowledge policy。
