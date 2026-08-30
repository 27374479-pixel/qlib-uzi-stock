---
description: qlib量化选股 + UZI深度分析 工作流规则
globs: "**/*.py"
---

# qlib + UZI 量化选股深度分析

## Cursor Skills（已配置）

项目级 skills 在 `.cursor/skills/`（Cursor 启动时自动发现，也可用 `/` 手动调用）：

| Skill | 用途 |
|-------|------|
| `qlib` | Microsoft Qlib 选股 / Alpha158 / LightGBM / pipeline |
| `uzi` | UZI 总入口 |
| `deep-analysis` | 个股 6-Task 深度分析 |
| `investor-panel` | 投资大佬评审团 |
| `lhb-analyzer` | 龙虎榜 / 游资席位 |
| `trap-detector` | 杀猪盘检测 |

UZI 四个 skill 通过 junction 指向 `UZI-Skill/`，改源码即生效，无需复制。

## 项目结构

- `.venv/` — Python 3.11 虚拟环境 (所有依赖在D盘)
- `qlib_data/cn_data/` — qlib A股数据
- `UZI-Skill/` — UZI股票深度分析引擎
- `qlib_select.py` — qlib LightGBM选股脚本
- `run_pipeline.py` — 完整pipeline入口
- `output/` — 输出结果
- `models/` — 训练好的模型

## 工作流

1. **qlib选股**: 运行 `qlib_select.py` 用 Alpha158因子 + LightGBM 选出Top候选（遵循 `qlib` skill）
2. **UZI分析**: 对候选股逐一使用 UZI Skill 深度分析（遵循 `uzi` / `deep-analysis`）
3. **综合报告**: 输出到 `output/` 目录

## Python环境

始终使用项目虚拟环境:
```
D:\myproject\qlib_uzi_stock\.venv\Scripts\python.exe
```

## UZI Skill使用

- 聊天里可直接 `/uzi`、`/deep-analysis`、`/lhb-analyzer`、`/trap-detector`
- 或读取 `.cursor/skills/*/SKILL.md`（与 `UZI-Skill/` 同源）
- 快速扫描: `.venv\Scripts\python.exe UZI-Skill\run.py <股票代码> --no-browser`

## 注意事项

- C盘空间紧张，所有文件和缓存必须在D:\myproject\qlib_uzi_stock 目录下
- pip安装包时确保在虚拟环境中
