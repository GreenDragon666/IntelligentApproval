# CLAUDE.md

## 项目目标

对招标文件执行完整的智能合规审批：

1. `src/dir_extr/` 提取 PDF、Office、纯文本的分页文本、目录和章节；
2. `src/cont_match/` 将政策规则匹配到招标原文并生成正式 JSON；
3. `src/rule_check/` 根据规则表“检查方式”调用全局结构化执行器或本地 LLM 语义判定，输出审批报告。

`main.py` 是三步统一入口；`prepare_case.py` 保留为步骤一、二独立运行/排错入口；已有
`rules_matched.json` 可以通过 `main.py --input` 单独进入步骤三。

文档输入不允许手工指定 `case_id`。`--one_report_path` 处理单个文档，`--reports_path` 递归
处理目录下所有支持文档；每个文档自动分配新的 `reports/report_x/` 并复制原文件。
新的 `--one_report_path`/`--reports_path` 运行必须先覆盖根目录 `reports/`，使其只表示最近一次任务，
编号从 `report_1` 开始；`--input` 续跑不得清空正在读取的 reports。

## 硬约束

- 不调用外部模型 API；所有模型调用统一连接服务器本地 Qwen3-8B vLLM。
- 不自动启动模型服务，由用户手动运行 `scripts/serve_vllm_qwen3_8b.sh`。
- 不保留 CSV 转换逻辑；正式输入/中间接口使用约定 JSON。
- 步骤一、二不得写死义齿、医疗器械、RPS 或特定产品领域词汇。
- 同伴原始参考代码位于 `references/stage1+2/`，不导入生产调用链，也不随意修改。
- 不在运行时生成案件专用 Python checker；确定性逻辑必须位于全局执行器。
- `rule_raw` 决定审查主题；`rule_text` 的 `【法规依据】` 可作为具体法律要求参考，`【描述】`只可帮助 LLM 理解适用场景、不得单独新增判定条件，`【公式】`、开发说明和其他生成块不得参与召回或判定。
- “检查方式”包含“结构化数据检查”时必须走确定性执行器；其他方法走语义判定。
- 结构化阈值和比较方向必须从 `rule_raw + 法规依据` 派生并复核，不得读取生成公式。
- 结构化字段别名可由本地 LLM 映射，但金额、比例、日期等值必须由正则提取；生成字段未匹配不得直接返回 `insufficient_input`。
- 步骤二默认使用字符 TF-IDF 与本地 BGE-M3 混合召回，embedding 只决定候选相关度、不决定步骤三状态；每条规则最终 evidence 不得超过3条。
- `argparse` 的 `add_argument` 调用保持一行，不主动拆成多行排版。
- Office 文档优先通过 LibreOffice 临时转 PDF；不得覆盖或改写用户原文件。
- DOCX 无 LibreOffice 时允许 XML 文本降级，DOC/ODT/RTF/WPS 无转换器时必须明确报错。
- 每次完整规则校验在 `reports/summary_brief.md` 只生成一份运行级简报；每个案件保留详细 `results/summary.md`。所有状态写 LLM 分析和证据位置/双页码，通过规则不复制完整 evidence 原文。

## 模块归属

- `src/llm.py`：步骤二、三共享的本地模型客户端。
- `src/page_schema.py`：步骤一、二共享的内部数据类型。
- `src/rule_schema.py`：步骤二输出、步骤三输入的正式契约。
- `src/cont_match/pipeline.py`：步骤一、二的串联编排及正式匹配 JSON 输出。
- `src/engine.py`：案件级审批编排，由统一入口调用。
- `src/rule_check/`：步骤三检查方式路由、全局确定性执行器、语义判定、缓存、复核和报告。
- `scripts/run_batch.py`：接收输入目录并调用统一入口的批量模式。

## 输入契约

见 `docs/MATCHED_JSON.md` 和 `src/rule_schema.py`：

- `source` 只允许 `file`；
- `rule_id` 是整数序号；
- `rule_raw` 对应“重点排查情形”；
- `rule_text` 对应“触发逻辑公式”；
- `check_method` 对应“检查方式”；
- `structured_fields` 对应“结构化数据展示字段”；
- `evidence` 包含原文及 PDF/文件内两套页码。

## 本地模型

- 生成模型：Qwen3-8B；embedding 模型：本地 BGE-M3；
- 服务脚本：`scripts/serve_vllm_qwen3_8b.sh`；
- 默认接口：`http://localhost:8001/v1`；
- served model name：`Qwen3-8B`；
- 服务端变量使用 `LLM_*`，Python 客户端变量使用 `LOCAL_LLM_*`；
- 不要在自动测试中启动模型。
- 步骤二、三默认各并发4个请求；语义判定与结果解释使用 `/no_think` 和短 JSON 输出。

## 常用命令

```bash
# 完整三步流程（需先手动启动 vLLM）
python main.py \
  --one_report_path /incoming/招标文件2.pdf \
  --policy-rules /path/to/policy_rules.xlsx \
  --document-page-1-pdf-page 9 \
  --use-llm \
  --strict-llm

# 只运行步骤一、二
python main.py \
  --one_report_path /incoming/招标文件2.pdf \
  --policy-rules /path/to/policy_rules.xlsx \
  --document-page-1-pdf-page 9 \
  --use-llm \
  --preprocess-only

# 从已有 JSON 单独运行步骤三，并从当前规则表刷新检查方式
python main.py --input reports/report_2/matched/rules_matched.json --policy-rules /path/to/policy_rules.xlsx

# 步骤三只执行结构化规则，禁用语义 LLM
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --no-llm-check

# 单条规则重检并保留旧结果历史
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --rules 2 \
  --force-recheck

# 多案件批量完整运行
python scripts/run_batch.py \
  --reports_path /incoming/tenders \
  --policy-rules /path/to/policy_rules.xlsx \
  --use-llm \
  --strict-llm

# 测试
python -m unittest discover -s tests -v
```

完整部署、参数、缓存和回滚边界见 `README.md`，架构见 `docs/ARCHITECTURE.md`。
