# CLAUDE.md

## 项目目标

对招标文件做智能合规审批。`prepare_case.py` 完成 PDF 逐页提取、通用章节拆分、政策规则
候选召回和可选本地 Qwen3-7B 重排，生成
`reports/report_x/matched/rules_matched.json`；后续负责 checker 生成、复用、执行、报告汇总
和可选失败反馈迭代。

## 硬约束

- 不调用外部 API；模型由服务器本地 vLLM 提供。
- 不自动启动模型服务，由用户手动启动。
- 不保留 CSV 转换逻辑；正式输入直接是约定 JSON。
- 新步骤一、二不得写死义齿、医疗器械、RPS 或特定产品领域词汇。
- `stage1+2/` 是同伴原始参考代码，不直接导入生产调用链，也不在未确认时修改。
- 不得用手写业务 checker、模拟输入或伪造模型输出冒充生成流程。
- checker 生成时不能写死案件 evidence，必须跨案件复用。

## 输入契约

见 `docs/MATCHED_JSON.md` 和 `src/schema.py`：

- `source` 只允许 `file`。
- `rule_id` 是整数序号。
- `rule_raw` 对应“重点排查情形”。
- `rule_text` 对应“触发逻辑公式”。
- `evidence` 包含原文及 PDF/文件内两套页码。

## 常用命令

```bash
# 步骤一、二无模型跑通
python prepare_case.py \
  --case-id report_2 \
  --pdf reports/report_2/招标文件2.pdf \
  --rules reports/report_2/规则-招标文件2对应内容-全量校正.xlsx \
  --output reports/report_2/matched/rules_matched.generated.json \
  --document-page-1-pdf-page 9

# 无模型诊断
python main.py --input reports/report_2/matched/rules_matched.json --no-generate

# 完整流程（需用户已手动启动 vLLM）
python main.py --input reports/report_2/matched/rules_matched.json

# 启用 LLM 复核与反馈迭代
python main.py --input reports/report_2/matched/rules_matched.json --review

# 单条规则生成
python gen_checker.py \
  --input reports/report_2/matched/rules_matched.json \
  --rule-id 2 --force

# 本地测试
python -m unittest discover -s tests -v
```

## 本地模型

- 默认：Qwen2.5-Coder-3B-Instruct
- 可切换：Qwen2.5-Coder-14B-Instruct
- 服务脚本：`scripts/serve_llm_3b.sh` / `scripts/serve_llm_14b.sh`
- 步骤一、二语义匹配：Qwen3-7B，脚本 `scripts/serve_stage12_qwen3_7b.sh`
- 不要在自动测试中启动模型。

## 架构

详见 `docs/ARCHITECTURE.md`。
