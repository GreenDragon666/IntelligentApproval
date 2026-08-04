# 架构说明：步骤三「代码校验」

## 1. 边界

| 在步骤三内（`src/`） | 不在步骤三内 |
|---|---|
| 输入契约、checker 生成与注册、确定性执行、报告 | PDF 抽取、目录拆分、关键词匹配 |
| 本地模型客户端（编写期） | 自动启动模型服务 |

输入由**你按规则准备**（或上游步骤一/二产出），形态为 `TenderContext` JSON，放入 `data/inputs/`。

---

## 2. 两阶段

```
编写期（要本地模型，偶尔跑）
  rules/*.md + acceptance test
       → LangGraph: generate → validate →(fail retry)→ save
       → generated_checkers/*.py → 人工 review → src/checkers/

运行时（每份文件，默认不调代码生成模型）
  data/inputs/*.json (TenderContext)
       → engine.run(checkers)
       → reports/*.json + *.md
```

**当前状态（已清模拟数据）：**
- `src/checkers/` 为空，无手写试点 checker。
- `data/inputs/` 为空，无样例 JSON。
- 编写期流水线骨架在 `src/codegen/` + `gen_checker.py`；默认 3B；**服务需你手动起**。

---

## 3. `src/` 文件职责

| 文件 | 职责 |
|---|---|
| `schema.py` | `TenderContext` / `RuleResult` / `Status` / `Evidence`；JSON 读写 |
| `registry.py` | `@register(rule_id)` |
| `engine.py` | 逐规则执行 → `ApprovalReport`（无 checker 时结果为空） |
| `report.py` | JSON / Markdown |
| `llm.py` | `chat()` / `healthcheck()` → 本地 vLLM |
| `codegen/*` | generate → validate → save，失败带错误重试 |
| `checkers/` | 落库 checker 目录（当前仅空 `__init__.py`） |

根目录：`main.py`（运行时）、`gen_checker.py`（编写期）、`config.py`、`scripts/serve_llm_*.sh`。

---

## 4. 本地模型（3B 已配置，不自动跑）

| 项 | 值 |
|---|---|
| 权重 | `/home/zyl/public/LLM Library/Qwen2.5-Coder-3B-Instruct` |
| served name | `Qwen2.5-Coder-3B-Instruct` |
| base_url | `http://localhost:8000/v1` |
| 启动 | `bash scripts/serve_llm_3b.sh` |

14B：`/home/zyl/public/LLM Library/Qwen2.5-Coder-14B-Instruct`，`scripts/serve_llm_14b.sh`。

---

## 5. 输入 JSON 契约（你来准备）

```json
{
  "doc_name": "可选",
  "full_text": "可选，全文",
  "sections": { "项目概况": "..." },
  "fields": {
    "project_type": "信息系统/软件开发",
    "warranty_months": 12,
    "registered_capital_req": 50000000,
    "project_actual_capital_need": 20000000
  },
  "tables": {},
  "references": {}
}
```

字段以各规则 `【开发说明】→输入数据` 为准；缺字段 → 该规则 `NA`。

---

## 6. 测试

验收测试、回归测试均由后续按规则自备，放入 `tests/`（如 `tests/acceptance/rule_N_accept.py`）。  
不再保留 PDF 抽取辅助与手写 checker 单测。

---

## 7. 代码生成 loop

```
generate → validate(acceptance) ──pass──→ save
              │
              └── fail & attempts < N ──→ generate(prev_code + error)
```

N 默认 3（`CODEGEN_MAX_RETRIES`）。
