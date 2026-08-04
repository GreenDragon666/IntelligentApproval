# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目目标

对单位发布的**招标文件**做智能合规审批。整体技术路线三步：目录/关键词提取 → 关键词匹配 → **代码校验**。

**本仓库只负责步骤三「代码校验」。**  
`src/` 内不得混入 PDF 抽取、目录拆分、关键词匹配等上游能力；那些若需要，只能放在 `tests/` 作辅助。

核心约束：
- 不调用外部 API，大模型本地部署。
- 审批有时限 → **运行时**走确定性 checker；Code-Agent 用在**编写期**。

## 开发环境

- Conda 环境：**`approval`**
  ```bash
  source /home/zyl/miniconda3/etc/profile.d/conda.sh && conda activate approval
  ```
- 本地模型权重：
  - 3B（默认）：`/home/zyl/public/LLM Library/Qwen2.5-Coder-3B-Instruct`
  - 14B：`/home/zyl/public/LLM Library/Qwen2.5-Coder-14B-Instruct`
- 起服务脚本：`scripts/serve_llm_3b.sh`（**不要自动启动**，由用户手动执行）。
- 配置：`config.py` / 环境变量 `LOCAL_LLM_*`。

## 常用命令

```bash
# 运行时：结构化输入 → 报告（需 data/inputs 下自备 JSON；当前无内置 checker）
python main.py --input data/inputs/<your>.json --out reports/

# 编写期：需用户已手动起 vLLM；验收测试自备
python gen_checker.py --rule rules/rule_4.md --rule-id rule_4 --test tests/acceptance/rule_4_accept.py
```

## 步骤三边界（`src/` 内容）

| 路径 | 职责 |
|---|---|
| `schema.py` | `TenderContext` / `RuleResult` 契约；`from_json_file` 读入 |
| `registry.py` | `@register` 注册表 |
| `engine.py` / `report.py` | 运行时执行与报告 |
| `llm.py` | 本地 vLLM 客户端 |
| `codegen/` | 规则 → 代码 LangGraph 流水线（generate/validate/retry/save） |
| `checkers/` | 已 review 的 checker（目标由 codegen 产出后迁入；**当前为空**） |

**输入契约**：上游或用户按规则准备 JSON（`data/inputs/`），不是 PDF。  
规则源：`rules/rule_N.md`（【公式】+【开发说明】为准）。

## 规则优先级

- 当前专注可落地规则；**rule_1 / rule_5 可先略过**。
- **禁止**再为演示手写整套 checker 冒充生成路径；目标是打通**本地模型生成**。

## 架构文档

详见 `docs/ARCHITECTURE.md`。
