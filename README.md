# 招标文件智能审批 · 步骤三「代码校验」

根据法规/规则库对**已抽取好的招标内容**做合规校验，输出违规/预警/通过报告。

本仓库**只做步骤三**。目录/关键词提取、关键词匹配、PDF 解析均不在 `src/` 内。

## 设计要点

- **编写期**：本地模型（LangGraph）把 `rules/*.md` 生成 checker → 验收测试 loop → 人工 review → `src/checkers/`。
- **运行时**：只跑已注册的确定性 checker；不现场调代码生成模型。
- **全本地**：vLLM OpenAI 兼容接口；默认 3B，路径见 `config.py`。

## 当前状态

- `src/checkers/` **为空**（已清除手写试点 checker）。
- `data/inputs/` **为空**（由你按契约自行放入输入 JSON）。
- 下一步重点：用本地模型把「规则 → checker」编写期路径跑通。

## 目录

```
src/                 # 步骤三全部代码
  schema.py          # TenderContext / RuleResult 契约
  registry.py        # @register
  engine.py          # 运行时执行
  report.py          # 报告
  llm.py             # 本地 vLLM 客户端
  codegen/           # 规则 → 代码 流水线
  checkers/          # 生成并 review 后的 checker（当前空）
main.py              # 运行时：--input JSON → 报告
gen_checker.py       # 编写期：规则 md → 生成 checker（需手动起 vLLM）
config.py
rules/
data/inputs/         # 你准备的 TenderContext JSON（自备）
scripts/             # serve_llm_3b.sh / 14b（不自动启动）
tests/               # 验收测试等（自备）
```

## 环境

```bash
source /home/zyl/miniconda3/etc/profile.d/conda.sh && conda activate approval
pip install -r requirements.txt
# vllm 你已安装则可跳过
```

## 运行时（校验已有 checker；当前注册表为空）

```bash
# 先在 data/inputs/ 放入符合契约的 JSON，再：
python main.py --input data/inputs/你的文件.json --out reports/
```

`TenderContext` 字段：`doc_name`, `full_text`, `sections`, `fields`, `tables`, `references`。  
缺字段时对应规则返回 `NA`；无已注册 checker 时报告结果为空、overall=pass。

## 编写期（本地 3B，手动起服务）

```bash
bash scripts/serve_llm_3b.sh
# 另开终端：
python gen_checker.py \
  --rule rules/rule_4.md \
  --rule-id rule_4 \
  --test tests/acceptance/rule_4_accept.py   # 验收测试需自备
```

权重：`/home/zyl/public/LLM Library/Qwen2.5-Coder-3B-Instruct`（默认）。  
14B：`scripts/serve_llm_14b.sh` + `export LOCAL_LLM_MODEL=Qwen2.5-Coder-14B-Instruct`。
