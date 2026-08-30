---
name: qlib
description: >-
  Microsoft Qlib quantitative investment workflows for this project: init A-share
  data, Alpha158 features, LightGBM training/prediction, Top-N stock selection,
  backtest, and qrun YAML pipelines. Use when the user mentions qlib, Alpha158,
  LightGBM 选股, 量化选股, backtest, provider_uri, qrun, or CSI300/CSI500/CSI800.
---

# Microsoft Qlib · 本项目用法

AI-oriented Quant 平台（[microsoft/qlib](https://github.com/microsoft/qlib)）。本仓库用它做 **A 股因子选股**，候选再交给 UZI Skill 深度分析。

## 项目路径（必须遵守）

| 用途 | 路径 |
|------|------|
| 虚拟环境 Python | `D:\myproject\qlib_uzi_stock\.venv\Scripts\python.exe` |
| A 股数据 | `qlib_data/cn_data/`（`config.QLIB_DATA_DIR`） |
| 模型 | `models/lgb_alpha158.pkl` |
| 选股脚本 | `qlib_select.py` |
| 全流程 | `run_pipeline.py` |
| 输出 | `output/` |

所有缓存与包安装必须落在本项目目录（C 盘空间紧张）。改路径前先读 `config.py`。

## 何时用本 Skill

- 训练 / 加载 LightGBM、跑 Alpha158、输出 Top-N 候选
- `qlib.init`、取行情特征、写 `qrun` YAML、做回测
- 与 UZI 串联：先 qlib 选股，再 `/deep-analysis` 或 `run_pipeline.py`

个股基本面、评委、龙虎榜、杀猪盘 → 改用 `uzi` / `deep-analysis` / `lhb-analyzer` / `trap-detector`。

## 快速执行

```bash
# 默认 CSI300 Top-5 → UZI 快速分析
.venv\Scripts\python.exe run_pipeline.py

# 只选股
.venv\Scripts\python.exe qlib_select.py

# 指定市场与数量
.venv\Scripts\python.exe run_pipeline.py --market csi500 --top 10

# 跳过 qlib，直接分析给定代码
.venv\Scripts\python.exe run_pipeline.py --skip-qlib --tickers 600519 000858
```

## 初始化与取数

```python
import qlib
from qlib.constant import REG_CN
from qlib.data import D

qlib.init(provider_uri="D:/myproject/qlib_uzi_stock/qlib_data/cn_data", region=REG_CN)

# 日历与特征
cal = D.calendar(freq="day")
df = D.features(
    ["SH600519"],
    ["$close", "$volume", "Ref($close, 1)"],
    start_time="2020-01-01",
    end_time="2024-12-31",
)
```

本项目封装见 `qlib_select.init_qlib(provider_uri)`。

## 本仓库选股约定

`qlib_select.py` 固定范式：

1. **Handler**: `qlib.contrib.data.handler.Alpha158`
2. **Label**: `Ref($close, -2) / Ref($close, -1) - 1`（T+1 开盘买、T+2 开盘卖近似）
3. **Model**: LightGBM（`LGBModel`），权重存 `models/lgb_alpha158.pkl`
4. **市场**: `csi300` / `csi500` / `csi800`（脚本参数）
5. **输出**: `output/candidates_YYYYMMDD.json`，含代码、分数、排名

修改因子或标签时：保持与历史模型一致，或删除旧 pkl 后重训，并在输出 JSON 里注明模型版本。

## 标准 Workflow（代码块方式）

与官方 `examples/workflow_by_code.py` 一致的组件链：

1. `DatasetH` + Alpha158 handler + train/valid/test segments  
2. `model.fit(dataset)` → `SignalRecord` 生成预测  
3. 可选 `SigAnaRecord`（IC 等）/ `PortAnaRecord`（组合回测）  
4. 策略常用 `TopkDropoutStrategy`

YAML 一键跑：`qrun conf.yaml`（需已安装 qlib CLI）。本项目日常优先用 `qlib_select.py` / `run_pipeline.py`，不必新建 YAML，除非用户明确要求 `qrun`。

## 与 UZI 协作

```
qlib 选股 (Top-N) → output/candidates_*.json
                 → 对每只代码调用 UZI
                 → UZI 报告 / output/
```

- 快速扫描：`python UZI-Skill/run.py <代码> --no-browser`（用项目 venv）
- 深度分析：读取并遵循 `deep-analysis` skill（6-Task 流程）
- 入口总览：`uzi` skill（`UZI-Skill/SKILL.md`）

不要在 qlib 阶段编造基本面结论；分数只表示模型排序信号。

## Agent 规则

1. 优先复用 `qlib_select.py` / `run_pipeline.py` / `config.py`，避免平行造轮子。  
2. 运行前确认 `.venv` 可用且能 `import qlib`；不可用则先修复环境再跑。  
3. `provider_uri` 必须指向本仓库 `qlib_data/cn_data`，不要默认 `~/.qlib/...`。  
4. 选股结果写入 `output/`，不要散落在临时目录。  
5. 需要个股深度研究时切换到 UZI skills，不要只用模型分数下买卖建议。

## 参考

- 官方文档: https://qlib.readthedocs.io/  
- 仓库: https://github.com/microsoft/qlib  
- 本项目规则: `.cursor/rules/qlib-uzi-workflow.md`
